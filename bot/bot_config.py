"""Runtime configuration for the bot, read from the environment / .env.

Paths default to the sibling ``99N`` checkout so the bot reads the exact
snapshots the dashboard serves, and the exact Town Hall assets the frontend
uses (``assets/Town_Hall<level>.webp``).
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional; plain env vars still work
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_99N_DIR = BASE_DIR.parent / "99N"


def _path_env(name, default):
    value = os.getenv(name)
    return Path(os.path.expanduser(value)).resolve() if value else default


DATA_DIR = _path_env("DATA_DIR", DEFAULT_99N_DIR / "data")
ASSET_DIR = _path_env("ASSET_DIR", DEFAULT_99N_DIR / "assets")
CONFIG_DIR = _path_env("CONFIG_DIR", BASE_DIR / "config" / "guilds")

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
BOT_PREFIX = os.getenv("BOT_PREFIX", "!")
DEV_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")
CLAN_TAG = os.getenv("CLAN_TAG", "")
TIMEZONE = os.getenv("BOT_TIMEZONE", "Asia/Jakarta")

# Watchdog thresholds mirror scrapers/watchdog.py: 12 h without a scheduled
# run, 24 h without any data written.
MAX_RUN_AGE_HOURS = 12
MAX_SNAPSHOT_AGE_HOURS = 24

# How often the dispatcher looks for something new.
DISPATCH_INTERVAL_MINUTES = 5


def th_asset(level):
    """Absolute path of the Town Hall image for ``level``.

    Returns None when the asset is missing so the caller can send the embed
    without a picture instead of raising on a bad level.
    """
    try:
        level = int(level)
    except (TypeError, ValueError):
        return None
    if level < 1 or level > 19:
        return None
    path = ASSET_DIR / f"Town_Hall{level}.webp"
    return str(path) if path.exists() else None
