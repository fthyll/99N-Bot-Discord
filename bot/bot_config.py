"""Runtime configuration for the bot, read from the environment / .env.

The snapshots and Town Hall art are copied into this repo, so a plain checkout
runs without the 99N dashboard beside it. Set ``DATA_DIR``/``ASSET_DIR`` to
point at the live scraper output instead of the committed copy.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Snapshot and asset dirs shipping with the repo win over the sibling checkout:
# a fresh clone has no ../99N, and defaulting to a path that does not exist made
# every reader degrade to empty instead of reading the committed copy.
DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_ASSET_DIR = BASE_DIR / "assets"

try:
    from dotenv import load_dotenv
    # Anchor to the bot's own .env: the default search walks up from the cwd, so
    # launching from another directory silently skipped the file and every
    # setting fell back to its default.
    load_dotenv(BASE_DIR / ".env")
except ImportError:  # dotenv is optional; plain env vars still work
    pass


def _path_env(name, default):
    """Absolute env path, or resolved against BASE_DIR when relative.

    A relative ``DATA_DIR=../99N/data`` must mean the same thing no matter
    which directory the bot was launched from, so it is anchored to the bot
    itself rather than to ``os.getcwd()``.
    """
    value = os.getenv(name)
    if not value:
        return default
    path = Path(os.path.expanduser(value))
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


DATA_DIR = _path_env("DATA_DIR", DEFAULT_DATA_DIR)
ASSET_DIR = _path_env("ASSET_DIR", DEFAULT_ASSET_DIR)
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
