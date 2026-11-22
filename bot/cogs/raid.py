"""Raid commands: weekend summary, per-member loot, absentees."""

import discord
from discord.ext import commands

from bot import bot_config
from bot.embeds import GOLD, RED
from bot.formatting import coc_time, hours_until, num, truncate
from bot.snapshots import SnapshotReader


def raid_member_rows(raid):
    """One row per member: attacks used/limit and capital loot."""
    rows = []
    for member in (raid or {}).get("members") or []:
        rows.append({
            "name": member.get("name", "?"),
            "tag": member.get("tag", ""),
            "attacks": int(member.get("attacks") or 0),
            "limit": int(member.get("attackLimit") or 0),
            "bonus": int(member.get("bonusAttackLimit") or 0),
            "loot": int(member.get("capitalResourcesLooted") or 0),
        })
    rows.sort(key=lambda r: r["loot"], reverse=True)
    return rows


def raid_absentees(raid):
    """Members who made no raid attack."""
    return [r for r in raid_member_rows(raid) if r["attacks"] == 0]


def build_raid_embed(raid):
    embed = discord.Embed(title="🏰 Capital raid", color=GOLD)
    if not raid:
        embed.description = "No raid snapshot available."
        return embed
    embed.color = GOLD if raid.get("state") == "ended" else RED
    remaining = hours_until(raid.get("endTime"))
    embed.description = (
        f"**State**: {raid.get('state', '?')}\n"
        f"**Total loot**: {num(raid.get('capitalTotalLoot', 0))}\n"
        f"**Districts destroyed**: {raid.get('enemyDistrictsDestroyed', 0)}\n"
        f"**Attacks**: {num(raid.get('totalAttacks', 0))} · "
        f"**Raids completed**: {num(raid.get('raidsCompleted', 0))}"
    )
    if remaining is not None:
        embed.description += f"\n**Ends**: {coc_time(raid.get('endTime'))}"
    embed.add_field(name="Offensive reward", value=num(raid.get("offensiveReward", 0)), inline=True)
    embed.add_field(name="Defensive reward", value=num(raid.get("defensiveReward", 0)), inline=True)

    top = raid_member_rows(raid)[:3]
    lines = [
        f"{i + 1}. **{r['name']}** — {num(r['loot'])} loot, {r['attacks']} atk"
        for i, r in enumerate(top)
    ] or ["—"]
    embed.add_field(name="Top looters", value=truncate("\n".join(lines)), inline=False)
    embed.set_footer(text="99N War Room · capital raids")
    return embed


def build_raid_members_embed(raid):
    rows = raid_member_rows(raid)
    embed = discord.Embed(title="🏰 Raid participation", color=GOLD)
    if not rows:
        embed.description = "No raid participants in this snapshot."
        return embed
    lines = [
        f"**{r['name']}** — {r['attacks']}/{r['limit'] or '?'} attacks, {num(r['loot'])} loot"
        for r in rows[:40]
    ]
    embed.description = truncate("\n".join(lines))
    embed.set_footer(text=f"{len(rows)} participants")
    return embed


def build_absentees_embed(raid):
    absent = raid_absentees(raid)
    embed = discord.Embed(title="💤 Raid absentees", color=RED)
    if not absent:
        embed.description = "Everyone raided this weekend."
        return embed
    embed.description = truncate("\n".join(f"**{r['name']}**" for r in absent))
    embed.set_footer(text=f"{len(absent)} members made no attack")
    return embed


class RaidCog(commands.Cog, name="raid"):
    def __init__(self, bot):
        self.bot = bot
        self.reader = SnapshotReader(str(bot_config.DATA_DIR))

    @commands.hybrid_command(name="raid", description="Capital raid weekend summary")
    async def raid(self, ctx):
        await ctx.send(embed=build_raid_embed(self.reader.raid()))

    @commands.hybrid_command(name="raidmembers", description="Per-member raid attacks and loot")
    async def raidmembers(self, ctx):
        await ctx.send(embed=build_raid_members_embed(self.reader.raid()))

    @commands.hybrid_command(name="raidabsent", description="Members who made no raid attack")
    async def raidabsent(self, ctx):
        await ctx.send(embed=build_absentees_embed(self.reader.raid()))


async def setup(bot):
    await bot.add_cog(RaidCog(bot))
