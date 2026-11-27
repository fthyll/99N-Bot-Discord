"""Live Clash of Clans API reader — a drop-in replacement for SnapshotReader.

Why a subclass: every cog builds ``SnapshotReader(...)`` and calls nine methods
on it (``clan``, ``members``, ``war``, ``raid``, ``players``, ``warlog``,
``meta``, ``trends``, ``freshest_stamp``). The API answers the same nine
questions, so overriding them keeps all six cogs and the dispatcher untouched —
``DATA_DIR`` stops mattering only when ``USE_COC_API=1``.

Costs, measured against the endpoints the cogs actually need:

* ``/clans/{tag}`` carries the full ``memberList``, so ``clan()`` and
  ``members()`` are one request, not two.
* ``war``, ``warlog``, ``raid``, ``leaguegroup`` and ``goldpass/current`` are
  one request each.
* ``players()`` is the expensive one: ``/clans/{tag}`` memberList omits
  ``warStars``, ``bestTrophies`` and ``clanCapitalContributions``, so filling
  those needs one ``/players/{tag}`` per member — 50 requests on every tick.
  Hence the TTL cache: reusing a snapshot for ``COC_CACHE_SECONDS``
  (default 600) turns a 5-minute dispatch loop from 14k requests/day into
  1.4k, against a quota that is not public but is known to be per-token.

Supercell quirks this has to survive:

* Tokens are whitelisted per source IP. GitHub Actions cannot use the official
  host, which is why the scrapers default to the RoyaleAPI proxy; the bot
  supports ``COC_API_BASE_URL`` for the same reason.
* ``/currentwar`` returns **404 notInWar** between wars. That is a normal
  state, not an error, and must yield ``{}`` so ``war`` commands say "no war"
  instead of raising.
* ``/warlog`` returns **403** when the clan keeps its log private.
* Only 429 and 5xx are retried. 403 (bad token / IP not whitelisted) and 404
  are reported immediately — retrying them burns quota to reach the same
  answer.

No new dependency: stdlib ``urllib`` already does everything ``requests`` would
here, and the bot ships with only ``discord.py`` and ``python-dotenv``.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from bot.snapshots import SnapshotReader

# 525 is Cloudflare's "SSL handshake failed"; 521/522/524 are its other
# upstream-unreachable codes. They arrive from the proxy in front of the API,
# so they are transient like any 5xx.
RETRYABLE = frozenset({429, 500, 502, 503, 504, 521, 522, 524, 525})
ATTEMPTS = 3
BACKOFF = (2, 5)
TIMEOUT = 30

# The Clan War League table needs one request per finished war in the group.
# A season is 7 rounds and 8 clans, so an unbounded fan-out is 28 requests on
# a single command. Cap it and keep the partial table: a truncated standings
# board beats a command that appears hung.
MAX_LEAGUE_WARS = 12


class CocApiError(RuntimeError):
    """The API refused for a reason retrying will not fix."""


def _iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CocClient(SnapshotReader):
    """CoC API reader. Same interface as SnapshotReader, live data.

    ``data_dir`` is still required because ``trends()`` has no API equivalent:
    time series only exist in the scraper archive, so the client falls back to
    the committed ``player_trends.json`` for that one method.
    """

    def __init__(self, data_dir, token, clan_tag, base_url=None,
                 cache_seconds=600, player_limit=None):
        super().__init__(data_dir)
        if not token:
            raise CocApiError(
                "COC_API_TOKEN is empty. Create a token at "
                "https://developer.clashofclans.com and whitelist this "
                "machine's IP."
            )
        tag = (clan_tag or "").strip()
        if not tag:
            raise CocApiError("CLAN_TAG is empty; set it to your clan tag, e.g. #2J0YP2LQL.")
        self.token = token
        self.clan_tag = tag  # with '#', as the API documents it
        self._encoded_tag = urllib.parse.quote(tag.lstrip("#"))
        self.base_url = (base_url or "https://api.clashofclans.com/v1").rstrip("/")
        self.cache_seconds = max(0, int(cache_seconds))
        # None means "all members"; an int exists so a slow command can be
        # bounded without editing code.
        self.player_limit = player_limit
        self._cache = {}
        # method -> why the live call failed and a snapshot was served instead.
        self.last_errors = {}

    # -- transport ---------------------------------------------------------
    def _get(self, path):
        """One request, retrying only what is worth retrying.

        Blocking by design: callers that must not stall the bot wrap this in
        ``asyncio.to_thread`` (see ``bot/offload.py``).
        """
        url = f"{self.base_url}{path}"
        last = None
        for attempt in range(1, ATTEMPTS + 1):
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    return response.getcode(), json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                status = exc.code
                body = exc.read().decode("utf-8", "replace")[:200]
                if status not in RETRYABLE or attempt == ATTEMPTS:
                    return status, _maybe_json(body)
                last = f"HTTP {status}"
            except (urllib.error.URLError, OSError) as exc:
                last = f"{type(exc).__name__}"
                if attempt == ATTEMPTS:
                    raise CocApiError(f"{url} unreachable: {exc}") from exc
            time.sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
        raise CocApiError(f"{url} failed after {ATTEMPTS} attempts ({last})")

    def _cached(self, key, fetch, force=False):
        """Memoise ``fetch()`` for ``cache_seconds``. 0 disables the TTL.

        ``force=True`` skips the freshness check but still stores, so a forced
        refresh refills the cache without ever leaving readers a gap where the
        cache is empty and a cog would fetch inline.

        Not thread-safe by design: WarmCache serialises its own refreshes, and
        cog reads that miss only ever write one dict entry, which the GIL
        makes atomic.
        """
        now = time.monotonic()
        hit = self._cache.get(key)
        if not force and hit is not None and self.cache_seconds and now - hit[0] < self.cache_seconds:
            return hit[1]
        value = fetch()
        self._cache[key] = (time.monotonic(), value)
        return value

    def invalidate(self):
        """Drop the cache so the next command hits the API."""
        self._cache.clear()

    # -- snapshots the API serves directly --------------------------------
    def _fallback(self, method_name, reason=None):
        """Committed snapshot for ``method_name`` when the live API fails.

        A rotated token, a changed egress IP or a transient Supercell outage
        must degrade to slightly older data rather than showing an error in
        Discord. The failure is recorded in ``last_errors`` so ``/freshness``
        can report *which* endpoint broke — a silent fallback would look like
        fresh data and hide a dead token indefinitely.
        """
        if reason:
            self.last_errors[method_name] = reason
        # Explicit class reference, not super(): these run inside closures
        # where zero-argument super() has no __class__ cell.
        fallback_fn = getattr(SnapshotReader, method_name, None)
        return fallback_fn(self) if callable(fallback_fn) else {}

    def clear_errors(self):
        self.last_errors = {}

    def clan(self, force=False):
        """``/clans/{tag}`` — includes ``memberList``, so this feeds members()."""

        def fetch():
            try:
                status, body = self._get(f"/clans/{self._encoded_tag}")
            except CocApiError:
                return self._fallback("clan", "unreachable")
            if status == 404:
                raise CocApiError(
                    f"Clan {self.clan_tag} not found; check CLAN_TAG."
                )
            if status != 200:
                return self._fallback("clan", f"HTTP {status}")
            return body if isinstance(body, dict) else {}

        return self._cached("clan", fetch, force=force)

    def members(self, force=False):
        clan = self.clan(force=force)
        return clan.get("memberList") or clan.get("members") or []

    def war(self, force=False):
        """Current war. 404 ``notInWar`` is a normal state, not a failure."""

        def fetch():
            try:
                status, body = self._get(f"/clans/{self._encoded_tag}/currentwar")
            except CocApiError:
                return self._fallback("war", "unreachable")
            if status == 200:
                return body if isinstance(body, dict) else {}
            reason = (body or {}).get("reason") if isinstance(body, dict) else None
            if status == 404 and reason == "notInWar":
                return {}
            # 403 (private log) and anything else: use the last snapshot.
            return self._fallback("war", f"HTTP {status}")

        return self._cached("war", fetch, force=force)

    def raid(self, force=False):
        """Newest capital raid weekend.

        ``/capitalraidseasons`` returns ``items`` newest-first, so the first
        entry is the current one. An empty list means the clan has never
        raided — the API answers 200, not 404.
        """

        def fetch():
            try:
                status, body = self._get(
                    f"/clans/{self._encoded_tag}/capitalraidseasons?limit=10"
                )
            except CocApiError:
                return self._fallback("raid", "unreachable")
            if status != 200:
                return self._fallback("raid", f"HTTP {status}")
            items = (body or {}).get("items") or []
            return items[0] if items else {}

        return self._cached("raid", fetch, force=force)

    def warlog(self, force=False):
        """``items`` from the war log. A private log is 403, not an error page."""

        def fetch():
            try:
                status, body = self._get(f"/clans/{self._encoded_tag}/warlog?limit=50")
            except CocApiError:
                return self._fallback("warlog", "unreachable")
            if status != 200:
                return self._fallback("warlog", f"HTTP {status}")
            return (body or {}).get("items") or []

        return self._cached("warlog", fetch, force=force)

    def player(self, tag):
        """Fetch a single player profile live (1 request instead of 50)."""
        if not tag:
            return {}
        try:
            status, body = self._get(
                f"/players/{urllib.parse.quote(str(tag).lstrip('#'))}"
            )
        except CocApiError:
            snap = self._fallback("players", "unreachable")
            return snap.get(tag) if isinstance(snap, dict) else {}
        if status == 200 and isinstance(body, dict):
            return body
        snap = self._fallback("players", f"HTTP {status}")
        return snap.get(tag) if isinstance(snap, dict) else {}

    def players(self, force=False):
        """Per-player profiles keyed by tag.

        One ``/players/{tag}`` per member because the clan payload omits
        ``warStars``, ``bestTrophies`` and ``clanCapitalContributions``. Cached
        for ``cache_seconds``; a single failing member is skipped rather than
        aborting the leaderboard.
        """

        def fetch():
            roster = self.members(force=force)
            if self.player_limit is not None:
                roster = roster[: self.player_limit]
            players = {}
            for member in roster:
                tag = member.get("tag")
                if not tag:
                    continue
                try:
                    status, body = self._get(
                        f"/players/{urllib.parse.quote(tag.lstrip('#'))}"
                    )
                except CocApiError:
                    continue
                if status == 200 and isinstance(body, dict):
                    players[tag] = body
            if not players:
                # Every profile lookup failed. An empty dict would silently
                # blank /topplayers and /member; the committed snapshot keeps
                # them populated (minus warStars, which the API is the only
                # source for).
                return self._fallback("players", "no profile lookup succeeded")
            return players

        return self._cached("players", fetch, force=force)

    def meta(self, force=False):
        """The slow-changing context the dashboard shows.

        Mirrors the shape ``scrapers/meta_scraper.py`` writes so the ``/cwl``
        command and the freshness chip read identical fields from either source.
        Each block fails independently: partial meta beats no meta.
        """

        def fetch():
            meta = {
                "fetchedAt": _iso_now(),
                "source": "coc-api",
                "goldpass": {},
                "countryRank": {},
                "cwl": {"state": "notInSeason"},
            }
            try:
                status, body = self._get("/goldpass/seasons/current")
                if status == 200 and isinstance(body, dict):
                    meta["goldpass"] = body
            except CocApiError:
                pass

            clan = self.clan(force=force)
            location = clan.get("location") or {}
            meta["countryRank"] = {
                "locationId": location.get("id"),
                "locationName": location.get("name"),
                "rank": None,
                "scanned": 0,
                # NOTE: the API's trophy ranking is a separate paginated
                # endpoint. Wire it in only if someone asks for the chip.
                "trophies": clan.get("clanPoints") or 0,
                "warLeague": clan.get("warLeague"),
            }
            meta["cwl"] = self._cwl(clan)
            return meta

        return self._cached("meta", fetch, force=force)

    # -- CWL ---------------------------------------------------------------
    def _cwl(self, clan):
        """League group standings, or a state marker when out of season."""
        try:
            status, group = self._get(
                f"/clans/{self._encoded_tag}/currentwar/leaguegroup"
            )
        except CocApiError as exc:
            return {"state": "unavailable", "error": str(exc)}
        if status == 404:
            return {"state": "notInSeason"}
        if status != 200 or not isinstance(group, dict):
            return {"state": "unavailable", "httpStatus": status}

        return {
            "state": group.get("state"),
            "season": group.get("season"),
            "standings": self._standings(group, clan),
        }

    def _standings(self, group, clan):
        """One row per clan, derived from the finished wars in the group.

        Every clan sees the same war from its own side, so each war is counted
        once — by the side whose ``tag`` sorts first — otherwise every result
        appears twice and the table doubles.
        """
        our_tag = clan.get("tag") or self.clan_tag
        rounds = group.get("rounds") or []
        tags = []
        for rnd in rounds:
            for war_tag in rnd.get("warTags") or []:
                if war_tag and war_tag != "#0" and war_tag not in tags:
                    tags.append(war_tag)
        tags = tags[:MAX_LEAGUE_WARS]

        table = {}
        for war_tag in tags:
            try:
                status, war = self._get(
                    f"/clanwarleagues/wars/{urllib.parse.quote(war_tag.lstrip('#'))}"
                )
            except CocApiError:
                continue
            if status != 200 or not isinstance(war, dict):
                continue
            sides = [war.get("clan") or {}, war.get("opponent") or {}]
            sides = [s for s in sides if s.get("tag")]
            if len(sides) != 2:
                continue
            # Count this war once, from the lower tag's perspective.
            if sides[0]["tag"] > sides[1]["tag"]:
                sides.reverse()
            left, right = sides
            if not left.get("stars") and not right.get("stars"):
                continue  # not played yet
            winner = (war.get("winner") or "").lower()
            for side, other, won in ((left, right, winner == "clan"),
                                     (right, left, winner == "opponent")):
                tag = side["tag"]
                row = table.setdefault(
                    tag, {"tag": tag, "name": side.get("name"), "wins": 0,
                          "draws": 0, "losses": 0, "stars": 0}
                )
                row["stars"] += side.get("stars") or 0
                if winner == "tie":
                    row["draws"] += 1
                elif won:
                    row["wins"] += 1
                else:
                    row["losses"] += 1

        rows = sorted(
            table.values(),
            key=lambda r: (r["wins"] * 3 + r["draws"], r["stars"]),
            reverse=True,
        )
        for index, row in enumerate(rows, 1):
            row["position"] = index
        # Our clan first in the sort when tied on everything else.
        for row in rows:
            row["isOurs"] = row["tag"] == our_tag
        return rows

    # -- things the API cannot answer -------------------------------------
    def trends(self):
        """No API equivalent — ``player_trends.json`` is scraper history."""
        return super().trends()

    def freshest_stamp(self):
        """Now, because this data is live. Keeps the staleness chip honest."""
        return _iso_now()


def _maybe_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {"raw": text}


def build_reader(data_dir, token=None, clan_tag=None, base_url=None,
                 cache_seconds=600):
    """Return the API client when configured, else the offline snapshot reader.

    One factory so ``bot.py``, the cogs and the dispatcher all agree on which
    source is active without each of them re-reading the environment.
    """
    if token:
        return CocClient(
            data_dir,
            token=token,
            clan_tag=clan_tag,
            base_url=base_url,
            cache_seconds=cache_seconds,
        )
    return SnapshotReader(data_dir)