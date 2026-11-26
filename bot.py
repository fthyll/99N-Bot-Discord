import asyncio
import logging
import sys

import discord
from discord.ext import commands

from bot import bot_config
from bot.cogs.admin import AdminCog
from bot.cogs.clan import ClanCog
from bot.cogs.player import PlayerCog
from bot.cogs.raid import RaidCog
from bot.cogs.war import WarCog
from bot.discord_log import attach_discord_log
from bot.logging_setup import LOGGER_NAME, setup_logging
from bot.notifier import Dispatcher

COGS = (ClanCog, PlayerCog, WarCog, RaidCog, AdminCog)

log = logging.getLogger(LOGGER_NAME)


class NinetyNineBot(commands.Bot):
    """Bot subclass so ``setup_hook`` is the real discord.py hook.

    Assigning ``bot.setup_hook = lambda: ...`` outside the class looked like it
    worked but was never awaited by the library startup path.
    """

    def __init__(self):
        intents = discord.Intents.default()
        # Every command is a hybrid_command, so slash is enough. Prefix parsing
        # is the only consumer of message_content, and it needs a privileged
        # intent that then has to stay ON in the Developer Portal. Set
        # BOT_PREFIX to re-enable both.
        if bot_config.BOT_PREFIX:
            intents.message_content = True
        # An empty prefix list tells discord.py there are no prefix commands, so
        # it stops warning about the missing privileged intent. Passing "!" as
        # a fallback while message_content is off is what produced the warning.
        super().__init__(command_prefix=bot_config.BOT_PREFIX or [], intents=intents)
        self.dispatcher = None
        self._dispatch_task = None

    async def setup_hook(self):
        for cog in COGS:
            await self.add_cog(cog(self))
            log.info("cog loaded: %s", cog.__name__)

        # Warm the API cache (or read snapshots) before the first command can
        # arrive; no-op in snapshot mode.
        reader = bot_config.start_reader()
        log.info("reader ready: %s", type(reader).__name__)

        guild_id = bot_config.DEV_GUILD_ID
        try:
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("synced %d commands to guild %s", len(synced), guild_id)
            else:
                synced = await self.tree.sync()
                log.info("synced %d commands globally", len(synced))
        except discord.HTTPException as exc:
            # A sync failure costs the slash commands, not the bot: the
            # gateway session and the dispatcher are still worth keeping up,
            # and a rate-limited sync succeeds on the next restart.
            log.error("command sync failed: %s", exc)

        # Optional mirror into a Discord channel. Attached after the gateway
        # session exists, because the handler resolves the channel through it.
        if bot_config.LOG_CHANNEL_ID:
            attach_discord_log(bot_config.LOG_CHANNEL_ID, self, level=logging.INFO)
            log.info("log mirroring to channel %s", bot_config.LOG_CHANNEL_ID)

        self.dispatcher = Dispatcher(self)
        self._dispatch_task = asyncio.create_task(self._run_dispatcher())

    async def _run_dispatcher(self):
        await self.wait_until_ready()
        try:
            self.dispatcher.prime()
        except Exception as exc:
            log.exception("dispatcher prime failed: %s", exc)
        while not self.is_closed():
            try:
                sent = await self.dispatcher.tick()
                if sent:
                    log.info("dispatcher delivered %d message(s)", sent)
            except Exception as exc:  # never let the loop die
                log.exception("dispatcher tick failed: %s", exc)
            await asyncio.sleep(bot_config.DISPATCH_INTERVAL_MINUTES * 60)

    async def on_command(self, ctx):
        """Log every prefix and slash invocation.

        ``on_command`` fires for both hybrid forms. A failing command is logged
        by ``on_command_error`` separately, so this line is the "who ran what"
        record rather than the error one.
        """
        where = getattr(ctx.guild, "name", "DM")
        log.info(
            "command /%s by %s in %s (%s)",
            ctx.command.qualified_name if ctx.command else "?",
            ctx.author,
            where,
            "slash" if ctx.interaction else "prefix",
        )
        # Activity-triggered freshness: a command means a human is looking at
        # the data right now, so nudge the warm thread to refresh ahead of its
        # timer. The nudge coalesces and refreshes off the loop, so a burst of
        # commands costs one refresh, not one per command.
        warmer = getattr(bot_config.build_reader(), "refresh_soon", None)
        if callable(warmer):
            warmer()

    async def on_command_error(self, ctx, error):
        """Record failures instead of letting them vanish into the console."""
        if isinstance(error, commands.CommandNotFound):
            return  # a typo in a chat message is not worth a log line
        log.error(
            "command /%s failed: %s",
            ctx.command.qualified_name if ctx.command else "?",
            error,
            exc_info=not isinstance(error, (commands.UserInputError, commands.CheckFailure)),
        )
        # The old behaviour was silence; tell the caller something went wrong
        # without leaking a traceback into the channel.
        if isinstance(error, commands.UserInputError):
            try:
                await ctx.send(f"❌ {error}", ephemeral=True)
            except discord.HTTPException:
                pass


def create_bot():
    return NinetyNineBot()


def main():
    setup_logging(level=getattr(logging, bot_config.LOG_LEVEL))
    log.info("99N bot starting (python %s)", sys.version.split()[0])

    if not bot_config.BOT_TOKEN:
        log.error("DISCORD_BOT_TOKEN is not set. Set it in .env before running.")
        sys.exit(1)

    log.info(
        "mode: %s | clan: %s | prefix: %r | log level: %s",
        "live API" if bot_config.COC_API_TOKEN else "snapshots",
        bot_config.CLAN_TAG or "(unset)",
        bot_config.BOT_PREFIX,
        bot_config.LOG_LEVEL,
    )

    bot = create_bot()

    @bot.event
    async def on_ready():
        log.info("logged in as %s (ID: %s)", bot.user, bot.user.id)
        log.info("serving %d guild(s)", len(bot.guilds))

    bot.run(bot_config.BOT_TOKEN)


if __name__ == "__main__":
    main()
