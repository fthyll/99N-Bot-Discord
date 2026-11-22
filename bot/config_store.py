"""Per-guild bot configuration.

Config (what the user wants) is kept separate from runtime state (what has
already been sent) so that re-configuring an event never loses the
anti-spam history and a bot restart never re-announces yesterday's war.

Defaults live here in code rather than in a second JSON file: one place to
edit, no chance of the two drifting apart.
"""

import copy
import json
import os
from datetime import time


def _event(enabled=True, channel_id=None, ping_role_id=None):
    return {
        "enabled": enabled,
        "channel_id": channel_id,
        "ping_role_id": ping_role_id,
    }


DEFAULT_CONFIG = {
    "events": {
        "war.preparation": _event(),
        "war.result": _event(),
        "war.ending_soon": _event(),
        "war.attack_reminder": _event(),
        "war.cleanup": _event(),
        "raid.start": _event(),
        "raid.summary": _event(),
        "raid.reminder": _event(),
        "clan.roster": _event(),
        "clan.donation_reset": _event(),
        "clan.donation_weekly": _event(),
        "clan.inactive": _event(),
        "cwl.round": _event(),
        "system.stale": _event(),
    },
    "quiet_hours": {
        "enabled": True,
        "start": "23:00",
        "end": "07:00",
    },
    "timezone": "Asia/Jakarta",
}


def _deep_merge(base, override):
    """overlay wins; nested dicts merge, everything else replaces."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _parse_hhmm(value):
    """'23:00' -> time(23, 0). Returns None on garbage."""
    try:
        hh, mm = str(value).split(":")
        return time(int(hh), int(mm))
    except (AttributeError, ValueError):
        return None


def in_quiet_window(now_time, start, end):
    """True when now_time falls inside [start, end).

    A window that wraps midnight (23:00 -> 07:00) covers both ends of the
    day; a window inside one day (09:00 -> 17:00) does not.
    """
    start_t = _parse_hhmm(start)
    end_t = _parse_hhmm(end)
    if start_t is None or end_t is None:
        return False
    if start_t == end_t:
        return False
    if start_t < end_t:
        return start_t <= now_time < end_t
    return now_time >= start_t or now_time < end_t


class ConfigStore:
    """Reads and writes per-guild config files under ``root``."""

    def __init__(self, root="config/guilds"):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _path(self, guild_id):
        return os.path.join(self.root, f"{guild_id}.json")

    def get(self, guild_id):
        """Merged config for one guild (defaults + that guild's overrides)."""
        path = self._path(guild_id)
        stored = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
            except (json.JSONDecodeError, OSError):
                stored = {}
        return _deep_merge(DEFAULT_CONFIG, stored)

    def _save(self, guild_id, cfg):
        path = self._path(guild_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, sort_keys=True)

    def set(self, guild_id, dotted_key, value):
        """Set one dotted key, e.g. 'events.war.result.enabled'.

        Event keys contain a dot themselves ('war.result'), so the path is
        resolved by longest-match rather than by splitting on every dot.
        """
        cfg = self.get(guild_id)
        parts = dotted_key.split(".")
        node = cfg
        rest = parts
        while len(rest) > 1:
            matched = None
            for i in range(len(rest), 0, -1):
                if ".".join(rest[:i]) in node:
                    matched = i
                    break
            if matched is None:
                break
            key = ".".join(rest[:matched])
            node = node[key]
            rest = rest[matched:]
        if len(rest) == 1:
            node[rest[0]] = value
        else:
            raise KeyError(dotted_key)
        self._save(guild_id, cfg)
        return cfg

    def set_channel(self, guild_id, event_key, channel_id):
        """Route one event, or every event, to a channel."""
        cfg = self.get(guild_id)
        if event_key == "all":
            for spec in cfg["events"].values():
                spec["channel_id"] = channel_id
        elif event_key in cfg["events"]:
            cfg["events"][event_key]["channel_id"] = channel_id
        else:
            raise KeyError(event_key)
        self._save(guild_id, cfg)
        return cfg

    def set_role(self, guild_id, event_key, role_id):
        cfg = self.get(guild_id)
        if event_key == "all":
            for spec in cfg["events"].values():
                spec["ping_role_id"] = role_id
        elif event_key in cfg["events"]:
            cfg["events"][event_key]["ping_role_id"] = role_id
        else:
            raise KeyError(event_key)
        self._save(guild_id, cfg)
        return cfg

    def set_quiet_hours(self, guild_id, enabled, start=None, end=None):
        cfg = self.get(guild_id)
        cfg["quiet_hours"]["enabled"] = enabled
        if start:
            cfg["quiet_hours"]["start"] = start
        if end:
            cfg["quiet_hours"]["end"] = end
        self._save(guild_id, cfg)
        return cfg

    def in_quiet_hours(self, guild_id, now_time):
        cfg = self.get(guild_id)
        qh = cfg["quiet_hours"]
        if not qh.get("enabled"):
            return False
        return in_quiet_window(now_time, qh.get("start"), qh.get("end"))
