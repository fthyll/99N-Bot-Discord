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

    A relative ``DATA_DIR=./data`` must mean the same thing no matter
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
# Empty by default: every command is a hybrid_command, so slash alone is
# enough, and prefix parsing would drag in the privileged Message Content
# intent. Set BOT_PREFIX=! to get text commands back (then also enable
# "Message Content Intent" in the Developer Portal).
BOT_PREFIX = os.getenv("BOT_PREFIX", "")
DEV_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")
CLAN_TAG = os.getenv("CLAN_TAG", "")
TIMEZONE = os.getenv("BOT_TIMEZONE", "Asia/Jakarta")

# Optional: mirror log lines into a Discord channel. Empty = file + console
# only, which is the default because a bot that posts its own logs unprompted
# is noise in every guild that did not ask for it.
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "")
# DEBUG / INFO / WARNING / ERROR — invalid values fall back to INFO.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
if LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    LOG_LEVEL = "INFO"

# Live Clash of Clans API, opt-in. Unset COC_API_TOKEN = read the committed
# snapshots, so a clone with no secrets still runs. See bot/coc_api.py for the
# request cost of each mode.
COC_API_TOKEN = os.getenv("COC_API_TOKEN", "")
COC_API_BASE_URL = os.getenv("COC_API_BASE_URL", "")
try:
    COC_CACHE_SECONDS = int(os.getenv("COC_CACHE_SECONDS", "600"))
except ValueError:
    COC_CACHE_SECONDS = 600


def _int_env(name, default=None):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# Cap the per-member profile fan-out; None means all members.
COC_PLAYER_LIMIT = _int_env("COC_PLAYER_LIMIT", None)

# Watchdog thresholds mirror scrapers/watchdog.py: 12 h without a scheduled
# run, 24 h without any data written.
MAX_RUN_AGE_HOURS = 12
MAX_SNAPSHOT_AGE_HOURS = 24

# How often the dispatcher looks for something new.
DISPATCH_INTERVAL_MINUTES = 5


_reader = None


def build_reader():
    """Snapshot reader or live API client, chosen by the environment.

    Memoised: every cog and the dispatcher ask for a reader, and a fresh
    ``CocClient`` per call would give each of the seven of them its own TTL
    cache — seven times the API traffic the cache exists to avoid.

    Imported lazily: ``bot.coc_api`` imports ``bot.snapshots``, so this keeps
    ``bot_config`` a leaf module nothing has to import around.
    """
    global _reader
    if _reader is None:
        from bot.coc_api import build_reader as _build

        _reader = _build(
            str(DATA_DIR),
            token=COC_API_TOKEN,
            clan_tag=CLAN_TAG,
            base_url=COC_API_BASE_URL or None,
            cache_seconds=COC_CACHE_SECONDS,
        )
        # Live mode: warm the cache on a background thread so no command ever
        # blocks the event loop on a socket. Snapshot mode needs nothing.
        if COC_API_TOKEN:
            from bot.offload import WarmCache

            _reader = WarmCache(
                _reader, interval_seconds=max(60, COC_CACHE_SECONDS - 60)
            )
    return _reader


def start_reader():
    """Start background work for the reader, if it has any. Idempotent."""
    reader = build_reader()
    starter = getattr(reader, "start", None)
    if callable(starter):
        starter()
    return reader


def reset_reader():
    """Drop the memoised reader so the next ``build_reader()`` rebuilds it."""
    global _reader
    stopper = getattr(_reader, "stop", None)
    if callable(stopper):
        try:
            stopper()
        except Exception:  # shutdown must not raise
            pass
    _reader = None


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
