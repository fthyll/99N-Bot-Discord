"""Logging setup for the bot: console + rotating file, stdlib only.

The whole process used to report through ``print()``, which meant a failure in
the dispatcher loop left no trace once the terminal scrolled past it and there
was no way to answer "did the war notification actually fire at 03:00?". One
``setup_logging()`` call at startup gives every module a real logger and keeps
``logs/bot.log`` as the durable record.
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from bot import bot_config

LOGGER_NAME = "99n"

# A war weekend of INFO lines fits comfortably; the rotation is there so a
# crash-looping bot cannot fill the disk overnight.
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 3
FORMAT = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers that are chatty at INFO. discord.py emits one line per
# gateway event at DEBUG and reconnection noise at INFO; our own lines are what
# the operator is looking for, so those stay at WARNING unless asked otherwise.
NOISY = ("discord", "discord.gateway", "discord.http", "discord.client")

_configured = False


def log_dir():
    """Where ``bot.log`` lives. ``BOT_LOG_DIR`` overrides the repo-local default."""
    override = os.getenv("BOT_LOG_DIR", "").strip()
    return Path(override) if override else bot_config.BASE_DIR / "logs"


def setup_logging(level=logging.INFO, console=True):
    """Install the handlers once, and return the bot's logger.

    Idempotent: calling it twice must not duplicate every line, and tests call
    it freely.
    """
    global _configured
    root = logging.getLogger()
    if not _configured:
        formatter = logging.Formatter(FORMAT, datefmt=DATEFMT)
        root.setLevel(level)

        if console:
            stream = logging.StreamHandler(sys.stdout)
            stream.setFormatter(formatter)
            root.addHandler(stream)

        try:
            directory = log_dir()
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                directory / "bot.log",
                maxBytes=MAX_BYTES,
                backupCount=BACKUPS,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            # A read-only checkout should still run; losing the file log beats
            # refusing to start.
            root.warning("file logging disabled: %s", exc)

        _configured = True
    else:
        root.setLevel(level)

    for name in NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
    return logging.getLogger(LOGGER_NAME)
