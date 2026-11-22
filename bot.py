import asyncio
import os
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


def create_bot():
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot = commands.Bot(command_prefix=bot_config.BOT_PREFIX, intents=intents)
    return bot


async def setup_hook(bot):
    # Load every cog before syncing the command tree.
    for cog in (ClanCog, PlayerCog, WarCog, RaidCog, AdminCog):
        await bot.add_cog(cog(bot))

    # Sync per-guild in development, globally on release.
    guild_id = bot_config.DEV_GUILD_ID
    if guild_id:
        guild = discord.Object(id=int(guild_id))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"Synced commands to guild {guild_id}.")
    else:
        await bot.tree.sync()
        print("Synced commands globally.")

    # Start the notification dispatcher.
    dispatcher = Dispatcher(bot)
    loop = asyncio.get_event_loop()

    async def run_dispatcher():
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                await dispatcher.tick()
            except Exception as exc:  # never let the loop die
                print(f"dispatcher: {exc}")
            await asyncio.sleep(bot_config.DISPATCH_INTERVAL_MINUTES * 60)

    bot.loop.create_task(run_dispatcher())


def main():
    if not bot_config.BOT_TOKEN:
        print("DISCORD_BOT_TOKEN is not set. Set it in .env before running.")
        sys.exit(1)

    bot = create_bot()
    bot.setup_hook = lambda: setup_hook(bot)

    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    bot.run(bot_config.BOT_TOKEN)


if __name__ == "__main__":
    main()
