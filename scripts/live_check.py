"""Start the real bot, prove it goes online, then shut down.

Used to verify the live startup path (gateway, command sync, dispatcher) and
that the log file records it. Exits 0 only if the bot actually reached ready.
"""

import asyncio
import logging
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

from bot import bot_config  # noqa: E402
from bot.logging_setup import log_dir, setup_logging  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("ninety9_entry", ROOT / "bot.py")
bot_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bot_module)

SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 20


async def main():
    setup_logging()
    log = logging.getLogger("99n.live")
    bot = bot_module.NinetyNineBot()

    ready = asyncio.Event()

    async def runner():
        try:
            await bot.start(bot_config.BOT_TOKEN)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("startup failed: %s: %s", type(exc).__name__, exc)
            ready.set()

    # Wait for the ready event rather than overriding on_ready: the bot does
    # not define one, and discord.py's own listener must keep working.
    @bot.listen("on_ready")
    async def _probe_ready():
        if not ready.is_set():
            log.info("LIVE: logged in as %s (guilds: %d, commands: %d)",
                     bot.user, len(bot.guilds), len(list(bot.tree.walk_commands())))
            ready.set()

    task = asyncio.create_task(runner())
    try:
        await asyncio.wait_for(ready.wait(), timeout=SECONDS)
    except asyncio.TimeoutError:
        log.error("LIVE: never reached ready within %ss", SECONDS)

    online = ready.is_set() and bot.is_ready()

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    if not bot.is_closed():
        await bot.close()

    for handler in logging.getLogger().handlers:
        handler.flush()

    path = log_dir() / "bot.log"
    print(f"\n--- log file: {path} ---")
    if path.exists():
        print("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]))
    print(f"\nONLINE={online}")
    return 0 if online else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
