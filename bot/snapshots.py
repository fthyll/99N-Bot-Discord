"""Reads the committed JSON snapshots the scrapers produce.

The bot never calls the Supercell API: it reads the same files the dashboard
serves, so the API token stays in the scraper environment and the bot cannot
outlive a token rotation.

Two index conventions live in the archive and they disagree:

* ``war_stats`` / ``raid_stats`` indices are oldest-first — the last entry is
  the newest snapshot.
* ``clan_stats`` / ``player_stats`` indices are newest-first — the *first*
  entry is the newest.

``latest()`` honours that difference instead of sorting by mtime, because a
fresh checkout or a restored backup gives every file the same timestamp.
"""

import json
import os
from datetime import datetime, timezone

# Folder whose *_index.json lists the newest snapshot first.
NEWEST_FIRST = frozenset({"clan_stats", "player_stats"})


def _parse_iso(value):
    """Parse an ISO stamp, tolerating the 'Z' suffix on Python < 3.11."""
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class SnapshotReader:
    def __init__(self, data_dir):
        self.data_dir = os.path.abspath(os.path.expanduser(data_dir))

    # -- internals ---------------------------------------------------------
    def _path(self, *parts):
        return os.path.join(self.data_dir, *parts)

    def _read_json(self, path):
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def index(self, folder):
        """Raw index list for a snapshot folder (may be empty)."""
        data = self._read_json(self._path(f"{folder}_index.json"))
        return data if isinstance(data, list) else []

    # -- public ------------------------------------------------------------
    def latest(self, folder):
        """Newest snapshot in ``folder`` as a dict ({} when there is none)."""
        names = self.index(folder)
        if names:
            name = names[0] if folder in NEWEST_FIRST else names[-1]
            data = self._read_json(self._path(folder, name))
            if data is not None:
                return data

        # Fallback for an archive with no index file: sort by the timestamp
        # embedded in the filename.
        candidates = []
        full = self._path(folder)
        if os.path.isdir(full):
            for name in os.listdir(full):
                if name.endswith(".json"):
                    candidates.append(name)
        if not candidates:
            return {}
        candidates.sort()
        return self._read_json(self._path(folder, candidates[-1])) or {}

    def members(self):
        """Member list from the newest clan snapshot."""
        clan = self.latest("clan_stats")
        return clan.get("memberList") or clan.get("members") or []

    def clan(self):
        return self.latest("clan_stats")

    def war(self):
        return self.latest("war_stats")

    def raid(self):
        return self.latest("raid_stats")

    def players(self):
        """Player profiles keyed by tag."""
        data = self.latest("player_stats")
        players = data.get("players") if isinstance(data, dict) else None
        return players if isinstance(players, dict) else {}

    def warlog(self):
        data = self._read_json(self._path("warlog_stats", "warlog.json"))
        if isinstance(data, dict):
            return data.get("items") or []
        return []

    def meta(self):
        return self._read_json(self._path("meta.json")) or {}

    def trends(self):
        return self._read_json(self._path("player_trends.json")) or {}

    def sync_time(self, kind):
        data = self._read_json(self._path(f"sync_{kind}.json")) or {}
        return data.get("fetchedAt")

    def age_hours(self, fetched_at, now=None):
        """Age of an ISO stamp in hours, or None when it cannot be read."""
        parsed = _parse_iso(fetched_at)
        if parsed is None:
            return None
        if now is None:
            now = datetime.now(timezone.utc)
        return (now - parsed).total_seconds() / 3600.0

    def freshest_stamp(self):
        """Newest of meta.fetchedAt and the two sync stamps.

        The freshness chip on the dashboard uses exactly this rule, so the bot
        and the page never disagree about how old the data is.
        """
        stamps = [
            self.meta().get("fetchedAt"),
            self.sync_time("war"),
            self.sync_time("raid"),
        ]
        parsed = [p for p in (_parse_iso(s) for s in stamps) if p]
        if not parsed:
            return None
        return max(parsed).isoformat().replace("+00:00", "Z")
