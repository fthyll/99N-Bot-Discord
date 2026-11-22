import asyncio
import sys

import discord
from discord.ext import commands

from bot import bot_config
from bot.cogs.admin import AdminCog
from bot.cogs.clan import ClanCog
from bot.cogs.player import PlayerCog
from bot.cogs.raid import RaidCog
from bot.cogs.war import WarCog
from bot.notifier import Dispatcher

COGS = (ClanCog, PlayerCog, WarCog, RaidCog, AdminCog)


class NinetyNineBot(commands.Bot):
    """Bot subclass so ``setup_hook`` is the real discord.py hook.

    Assigning ``bot.setup_hook = lambda: ...`` outside the class looked like it
    worked but was never awaited by the library startup path.
    """

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix=bot_config.BOT_PREFIX, intents=intents)
        self.dispatcher = None
        self._dispatch_task = None

    async def setup_hook(self):
        for cog in COGS:
            await self.add_cog(cog(self))

        guild_id = bot_config.DEV_GUILD_ID
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Synced commands to guild {guild_id}.")
        else:
            await self.tree.sync()
            print("Synced commands globally.")

        self.dispatcher = Dispatcher(self)
        self._dispatch_task = asyncio.create_task(self._run_dispatcher())

    async def _run_dispatcher(self):
        await self.wait_until_ready()
        try:
            self.dispatcher.prime()
        except Exception as exc:
            print(f"dispatcher prime: {exc}")
        while not self.is_closed():
            try:
                await self.dispatcher.tick()
            except Exception as exc:  # never let the loop die
                print(f"dispatcher: {exc}")
            await asyncio.sleep(bot_config.DISPATCH_INTERVAL_MINUTES * 60)


def create_bot():
    return NinetyNineBot()


def main():
    if not bot_config.BOT_TOKEN:
        print("DISCORD_BOT_TOKEN is not set. Set it in .env before running.")
        sys.exit(1)

    bot = create_bot()

    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    bot.run(bot_config.BOT_TOKEN)


if __name__ == "__main__":
    main()
