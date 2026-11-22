"""Notification dispatcher.

Runtime state (what has already been announced) lives in a separate file from
the guild config, so ``/notif set`` never wipes the anti-spam history and a
restart never re-announces yesterday's war.

One loop for the whole guild, not one per event: the snapshots are read once
per tick and handed to every trigger.

Markers are written only for events that were actually delivered. Writing them
for every observed state silently killed ``war.ending_soon`` and
``war.attack_reminder``: the first tick of a war claimed both markers hours
before either window opened, so each trigger found its own marker and stayed
quiet for the rest of the war.
"""

import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bot import bot_config
from bot.config_store import ConfigStore
from bot.events import NOTIFY_EVENTS
from bot.snapshots import SnapshotReader

# Markers record "this event was delivered for this war / raid / day". They are
# compared against the current snapshot, so a new war or a new day stops
# matching on its own and the marker cannot block a later window.
WAR_MARKERS = ("preparation_key", "ending_soon_key", "reminder_key", "cleanup_key")
RAID_MARKERS = ("reminder_key",)
CLAN_MARKERS = ("donation_weekly", "donation_reset", "inactive")


class StateStore:
    def __init__(self, root):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _path(self, guild_id):
        return os.path.join(self.root, f"{guild_id}.state.json")

    def get(self, guild_id):
        path = self._path(guild_id)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, guild_id, state):
        with open(self._path(guild_id), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)

    def clear(self, guild_id):
        path = self._path(guild_id)
        if os.path.exists(path):
            os.remove(path)


def build_context(reader, state, now=None):
    """Snapshot context handed to every trigger."""
    return {
        "war": reader.war(),
        "raid": reader.raid(),
        "clan": reader.clan(),
        "meta": reader.meta(),
        "reader": reader,
        "now": now or datetime.now(timezone.utc),
        "prev": state or {},
    }


def _carry(new, old, fields):
    """Copy markers that are still valid into the new state block."""
    for field in fields:
        if (old or {}).get(field):
            new[field] = old[field]
    return new


def mark_delivered(state, key, ctx):
    """Record that ``key`` was delivered, so it cannot fire again for this key."""
    now = ctx["now"]
    war_key = (ctx.get("war") or {}).get("startTime")
    if key == "war.preparation":
        state.setdefault("war", {})["preparation_key"] = war_key
    elif key in ("war.ending_soon", "war.attack_reminder", "war.cleanup"):
        field = {
            "war.ending_soon": "ending_soon_key",
            "war.attack_reminder": "reminder_key",
            "war.cleanup": "cleanup_key",
        }[key]
        state.setdefault("war", {})[field] = war_key
    elif key == "raid.reminder":
        state.setdefault("raid", {})["reminder_key"] = (ctx.get("raid") or {}).get("startTime")
    elif key == "clan.donation_weekly":
        state.setdefault("clan", {})["donation_weekly"] = now.strftime("%Y%m%d")
    elif key == "clan.donation_reset":
        state.setdefault("clan", {})["donation_reset"] = now.strftime("%Y%m%d")
    elif key == "clan.inactive":
        state.setdefault("clan", {})["inactive"] = now.strftime("%Y%m%d")
    elif key == "system.stale":
        state.setdefault("system", {})["stale"] = now.strftime("%Y%m%d%H")
    return state


def next_state(ctx, state, fired=()):
    """New runtime state after one tick.

    ``fired`` is the set of event keys delivered this tick. Only those get a
    marker; every other marker is carried over, so an early tick can never
    swallow a later event's window.
    """
    prev = state or {}
    now = ctx["now"]
    war = ctx.get("war") or {}
    raid = ctx.get("raid") or {}
    clan = ctx.get("clan") or {}
    meta = ctx.get("meta") or {}

    new = dict(prev)

    if war:
        new["war"] = _carry(
            {"state": war.get("state"), "key": war.get("startTime")},
            prev.get("war"), WAR_MARKERS,
        )
    else:
        new["war"] = {}

    if raid:
        new["raid"] = _carry(
            {"state": raid.get("state"), "key": raid.get("startTime")},
            prev.get("raid"), RAID_MARKERS,
        )
    else:
        new["raid"] = {}

    members = {m.get("tag"): m for m in (clan.get("memberList") or []) if m.get("tag")}
    if clan:
        new["clan"] = _carry(
            {
                "memberTags": sorted(members),
                "donations": {
                    "total": sum((m.get("donations") or 0) for m in members.values()),
                    "received": sum((m.get("donationsReceived") or 0) for m in members.values()),
                },
            },
            prev.get("clan"), CLAN_MARKERS,
        )
    else:
        new["clan"] = {}

    cwl = meta.get("cwl")
    new["cwl"] = {"state": cwl.get("state")} if isinstance(cwl, dict) and cwl else {}
    new["system"] = _carry({}, prev.get("system"), ("stale",))

    for key in fired or ():
        mark_delivered(new, key, ctx)

    new["savedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return new


def due_events(guild_id, config_store, reader, state, now=None):
    """(event_key, [embeds]) for every event that has something to say."""
    cfg = config_store.get(guild_id)
    ctx = build_context(reader, state, now=now)
    out = []
    for key, trigger in NOTIFY_EVENTS.items():
        spec = cfg["events"].get(key) or {}
        if not spec.get("enabled"):
            continue
        try:
            embeds = trigger(ctx, state)
        except Exception as exc:  # one bad trigger must not silence the rest
            print(f"notifier: {key} failed: {exc}")
            continue
        if embeds:
            out.append((key, embeds))
    return out


class Dispatcher:
    """Owns the loop that turns snapshot changes into channel messages."""

    def __init__(self, bot, reader=None, config_store=None, state_store=None):
        self.bot = bot
        self.reader = reader or SnapshotReader(str(bot_config.DATA_DIR))
        self.config = config_store or ConfigStore(str(bot_config.CONFIG_DIR))
        self.states = state_store or StateStore(str(bot_config.CONFIG_DIR))

    def _guild_ids(self):
        ids = []
        for filename in os.listdir(self.config.root):
            if not filename.endswith(".json") or filename.endswith(".state.json"):
                continue
            try:
                ids.append(int(filename[:-5]))
            except ValueError:
                continue
        return ids

    def _in_quiet_hours(self, guild_id, now):
        cfg = self.config.get(guild_id)
        try:
            tz = ZoneInfo(cfg.get("timezone") or "Asia/Jakarta")
        except Exception:
            tz = timezone.utc
        return self.config.in_quiet_hours(guild_id, now.astimezone(tz).time())

    def prime(self):
        """Record today's state without announcing anything.

        Runs once at startup. Without it a fresh install would read the archive
        for the first time and find a finished war, an ended raid, a donation
        reset and stale data all at once, then post every one of them.
        """
        now = datetime.now(timezone.utc)
        for guild_id in self._guild_ids():
            state = self.states.get(guild_id)
            ctx = build_context(self.reader, state, now=now)
            # Every event whose condition is already true is marked as if the
            # message had been delivered, but nothing is sent.
            already = [key for key, _ in due_events(guild_id, self.config, self.reader, state, now=now)]
            self.states.save(guild_id, next_state(ctx, state, fired=already))

    async def tick(self, now=None):
        """One pass: evaluate every guild, send what is due."""
        now = now or datetime.now(timezone.utc)
        sent = 0
        for guild_id in self._guild_ids():
            state = self.states.get(guild_id)
            cfg = self.config.get(guild_id)

            if self._in_quiet_hours(guild_id, now):
                continue

            delivered = []
            for key, embeds in due_events(guild_id, self.config, self.reader, state, now=now):
                spec = cfg["events"][key]
                channel = self.bot.get_channel(spec.get("channel_id") or 0)
                if channel is None:
                    continue  # unconfigured channel must not claim the marker
                content = f"<@&{spec['ping_role_id']}>" if spec.get("ping_role_id") else None
                ok = True
                for embed in embeds:
                    try:
                        await channel.send(content=content, embed=embed)
                        sent += 1
                    except Exception as exc:  # a bad channel must not stop the loop
                        print(f"notifier: send failed for {key}: {exc}")
                        ok = False
                if ok:
                    delivered.append(key)

            self.states.save(
                guild_id,
                next_state(build_context(self.reader, state, now), state, fired=delivered),
            )
        return sent
