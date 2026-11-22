"""Notification dispatcher.

Runtime state (what has already been announced) lives in a separate file from
the guild config, so ``/notif set`` never wipes the anti-spam history and a
restart never re-announces yesterday's war.

One loop for the whole guild, not one per event: the snapshots are read once
per tick and handed to every trigger.
"""

import json
import os
from datetime import datetime, timezone

from bot import bot_config
from bot.config_store import ConfigStore
from bot.events import NOTIFY_EVENTS
from bot.snapshots import SnapshotReader


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


def next_state(ctx, state):
    """New runtime state after one tick.

    Only what the triggers look at is kept, so the file stays small and
    hand-editable.
    """
    state = dict(state or {})
    war = ctx["war"]
    raid = ctx["raid"]
    clan = ctx["clan"]
    meta = ctx["meta"]
    now = ctx["now"]

    state["war"] = {
        "state": war.get("state"),
        "key": war.get("startTime"),
        "ending_soon_key": war.get("startTime") if war.get("state") == "inWar" else None,
        "reminder_key": war.get("startTime") if war.get("state") == "inWar" else None,
        "cleanup_key": war.get("startTime") if war.get("state") == "warEnded" else None,
    } if war else {}
    state["raid"] = {
        "state": raid.get("state"),
        "key": raid.get("startTime"),
        "reminder_key": raid.get("startTime") if raid.get("state") == "ongoing" else None,
    } if raid else {}
    members = {m.get("tag"): m for m in (clan.get("memberList") or []) if m.get("tag")}
    donations = state.get("clan", {}).get("donations") or {}
    state["clan"] = {
        "memberTags": sorted(members),
        "donations": {
            "total": sum((m.get("donations") or 0) for m in members.values()),
            "received": sum((m.get("donationsReceived") or 0) for m in members.values()),
            "lastSeen": now.strftime("%Y%m%d"),
        },
        "donation_weekly": state.get("clan", {}).get("donation_weekly"),
        "inactive": state.get("clan", {}).get("inactive"),
    } if clan else {}
    cwl = (meta or {}).get("cwl")
    state["cwl"] = {"state": cwl.get("state")} if isinstance(cwl, dict) and cwl else {}
    state["system"] = {"stale": state.get("system", {}).get("stale")}
    return state


def due_events(guild_id, config_store, reader, state, now=None):
    """(event_key, [embeds]) for every event that has something to say."""
    cfg = config_store.get(guild_id)
    ctx = build_context(reader, state, now=now)
    out = []
    for key, trigger in NOTIFY_EVENTS.items():
        spec = cfg["events"].get(key) or {}
        if not spec.get("enabled"):
            continue
        embeds = trigger(ctx, state)
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

    async def tick(self, now=None):
        """One pass: evaluate every guild, send what is due."""
        sent = 0
        for guild_id in self._guild_ids():
            state = self.states.get(guild_id)
            cfg = self.config.get(guild_id)
            now = now or datetime.now(timezone.utc)

            if self.config.in_quiet_hours(guild_id, now.astimezone(
                    __import__("zoneinfo").ZoneInfo(cfg.get("timezone") or "Asia/Jakarta")).time()):
                continue

            for key, embeds in due_events(guild_id, self.config, self.reader, state, now=now):
                spec = cfg["events"][key]
                channel = self.bot.get_channel(spec.get("channel_id") or 0)
                if channel is None:
                    continue
                for embed in embeds:
                    content = None
                    if spec.get("ping_role_id"):
                        content = f"<@&{spec['ping_role_id']}>"
                    try:
                        await channel.send(content=content, embed=embed)
                        sent += 1
                    except Exception as exc:  # a bad channel must not stop the loop
                        print(f"notifier: send failed for {key}: {exc}")
            self.states.save(guild_id, next_state(build_context(self.reader, state, now), state))
        return sent
