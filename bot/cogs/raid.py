"""Raid commands: weekend summary, per-member loot, absentees."""

import discord
from discord.ext import commands

from bot import bot_config
from bot.embeds import GOLD, RED
from bot.formatting import bar, coc_time, duration_text, hours_until, medal, num, pct, truncate


def raid_member_rows(raid):
    """One row per member: attacks used/capacity and capital loot.

    ``attacks`` in a raid payload counts the bonus attacks too, so the
    capacity has to be ``attackLimit + bonusAttackLimit`` — 5+1, not 5.
    Showing "6/5" was the old behaviour.
    """
    rows = []
    for member in (raid or {}).get("members") or []:
        limit = int(member.get("attackLimit") or 0)
        bonus = int(member.get("bonusAttackLimit") or 0)
        rows.append({
            "name": member.get("name", "?"),
            "tag": member.get("tag", ""),
            "attacks": int(member.get("attacks") or 0),
            "limit": limit,
            "bonus": bonus,
            "capacity": limit + bonus,
            "loot": int(member.get("capitalResourcesLooted") or 0),
        })
    rows.sort(key=lambda r: r["loot"], reverse=True)
    return rows


def raid_absentees(raid, members=None):
    """Members who made no raid attack.

    ``raid['members']`` only lists members who attacked at least once — the
    ones who never raided are absent from it entirely, so the clan roster has
    to be diffed in. Passing ``members`` doubles as the full clan list.
    """
    def key(entry):
        # Tag is the stable identity; the name is a fallback so a payload
        # without tags reports none absent instead of the whole clan.
        return entry.get("tag") or entry.get("name")

    attacked = {key(r) for r in raid_member_rows(raid) if r["attacks"] > 0}
    if not members:
        return [r for r in raid_member_rows(raid) if r["attacks"] == 0]
    rows = []
    for member in members:
        tag = key(member)
        if tag and tag not in attacked:
            rows.append({
                "name": member.get("name", "?"),
                "tag": member.get("tag", ""),
                "attacks": 0,
                "limit": None,
                "bonus": None,
                "loot": 0,
            })
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def build_raid_embed(raid):
    embed = discord.Embed(title="🏰 Capital raid", color=GOLD)
    if not raid:
        embed.description = "No raid snapshot available."
        return embed
    state = raid.get("state")
    embed.color = GOLD if state == "ended" else RED
    remaining = hours_until(raid.get("endTime"))
    rows = raid_member_rows(raid)
    total_loot = raid.get("capitalTotalLoot", 0)

    # Share of the weekend's loot that the top three accounted for — the number
    # that says whether the clan carried a few people or spread it evenly.
    top3_loot = sum(r["loot"] for r in rows[:3])
    lines = [
        f"**State** · {state or '?'}",
        f"**Total loot** · {num(total_loot)}",
        f"**Districts destroyed** · {raid.get('enemyDistrictsDestroyed', 0)}",
        f"**Attacks** · {num(raid.get('totalAttacks', 0))}   |   "
        f"**Raids completed** · {num(raid.get('raidsCompleted', 0))}",
    ]
    if rows:
        lines += [
            "",
            f"**Top 3 share** `{bar(top3_loot, total_loot, 12)}` {pct(top3_loot, total_loot)}",
        ]
    if remaining is not None:
        end = "ended" if remaining < 0 else f"in {duration_text(remaining)}"
        lines.append(f"**Ends** · {coc_time(raid.get('endTime'))} ({end})")
    embed.description = "\n".join(lines)

    embed.add_field(name="💰 Offensive reward", value=num(raid.get("offensiveReward", 0)), inline=True)
    embed.add_field(name="🛡️ Defensive reward", value=num(raid.get("defensiveReward", 0)), inline=True)
    if rows:
        embed.add_field(name="👥 Participants", value=str(len(rows)), inline=True)

    top = rows[:3]
    lines = [
        f"{medal(i)} **{r['name']}** — {num(r['loot'])} loot, {r['attacks']} atk"
        for i, r in enumerate(top, 1)
    ] or ["—"]
    embed.add_field(name="🏅 Top looters", value=truncate("\n".join(lines)), inline=False)
    embed.set_footer(text="99N War Room · capital raids")
    return embed


def build_raid_members_embed(raid, members=None):
    """Per-member raid line, plus how much of the roster actually showed up.

    ``members`` is the clan roster; the raid payload only lists members who
    attacked, so without it "no attacks" can only ever be zero.
    """
    rows = raid_member_rows(raid)
    embed = discord.Embed(title="🏰 Raid participation", color=GOLD)
    if not rows and not members:
        embed.description = "No raid participants in this snapshot."
        return embed
    peak = max((r["loot"] for r in rows), default=0)
    lines = [
        f"**{r['name']}** — {r['attacks']}/{r['capacity'] or '?'} atk, {num(r['loot'])} loot\n"
        f"`{bar(r['loot'], peak)}`"
        for r in rows[:40]
    ]
    embed.description = truncate("\n".join(lines)) or "No raid participants in this snapshot."

    idle = raid_absentees(raid, members) if members else []
    embed.add_field(name="Participants", value=str(len(rows)), inline=True)
    if members:
        embed.add_field(name="Absent", value=str(len(idle)), inline=True)
        embed.add_field(name="Turnout", value=pct(len(rows), len(members)), inline=True)
    elif rows:
        embed.add_field(name="Total attacks", value=num(sum(r["attacks"] for r in rows)), inline=True)
    if rows:
        embed.add_field(
            name="Avg loot",
            value=num(sum(r["loot"] for r in rows) // len(rows)),
            inline=True,
        )
    embed.set_footer(text=f"{len(rows)} participants")
    return embed


def build_absentees_embed(raid, members=None):
    absent = raid_absentees(raid, members)
    embed = discord.Embed(title="💤 Raid absentees", color=RED)
    if not absent:
        embed.description = "Everyone raided this weekend."
        return embed
    embed.description = truncate("\n".join(f"🔸 **{r['name']}**" for r in absent))
    roster = len(members or [])
    embed.add_field(name="Absent", value=str(len(absent)), inline=True)
    if roster:
        embed.add_field(name="Participation", value=pct(roster - len(absent), roster), inline=True)
    embed.set_footer(text=f"{len(absent)} members made no attack")
    return embed


class RaidCog(commands.Cog, name="raid"):
    def __init__(self, bot):
        self.bot = bot
        self.reader = bot_config.build_reader()

    @commands.hybrid_command(name="raid", description="Capital raid weekend summary")
    async def raid(self, ctx):
        await ctx.send(embed=build_raid_embed(self.reader.raid()))

    @commands.hybrid_command(name="raidmembers", description="Per-member raid attacks and loot")
    async def raidmembers(self, ctx):
        await ctx.send(embed=build_raid_members_embed(self.reader.raid(), self.reader.members()))

    @commands.hybrid_command(name="raidabsent", description="Members who made no raid attack")
    async def raidabsent(self, ctx):
        await ctx.send(embed=build_absentees_embed(self.reader.raid(), self.reader.members()))


async def setup(bot):
    await bot.add_cog(RaidCog(bot))
