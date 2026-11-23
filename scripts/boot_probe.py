"""Boot the bot without a real Discord token and prove logging works.

The bot reaches `client.login()` only after every cog loads and the command
tree is built, so this runs the real startup path with a stubbed network layer
and then exits — no gateway connection, no token needed.
"""

import asyncio
import logging
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.logging_setup import log_dir, setup_logging  # noqa: E402

# `import bot` would resolve to the bot/ package, not the bot.py entry point —
# load the entry file by path so this exercises the real startup object.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("ninety9_entry", ROOT / "bot.py")
bot_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bot_module)


async def main():
    setup_logging()
    log = logging.getLogger("99n.boot")
    log.info("boot probe: building the real bot object")

    bot = bot_module.NinetyNineBot()

    # The startup path a real launch takes, minus the gateway handshake.
    for cog in bot_module.COGS:
        await bot.add_cog(cog(bot))
    log.info("loaded %d cogs", len(bot.cogs))

    commands = [c.qualified_name for c in bot.tree.walk_commands()]
    log.info("command tree has %d commands: %s", len(commands), ", ".join(sorted(commands)))

    # Prove a failure is recorded where the operator can find it.
    try:
        raise RuntimeError("boot probe: simulated failure")
    except RuntimeError:
        log.exception("boot probe caught a failure as expected")

    for handler in logging.getLogger().handlers:
        handler.flush()

    # A channel id that does not exist must not break startup; the handler
    # simply finds no channel and drops the line.
    from bot.discord_log import attach_discord_log
    handler = attach_discord_log("1", bot)
    log.info("log mirror attached: %s", handler is not None)
    logging.getLogger().removeHandler(handler)

    path = log_dir() / "bot.log"
    print(f"\n--- log file: {path} (exists={path.exists()}) ---")
    if path.exists():
        tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
        print("\n".join(tail))

    await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
