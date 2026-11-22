"""Clan commands: overview card, roster, top, inactive members."""

import discord
from discord.ext import commands

from bot import bot_config
from bot.embeds import BLUE, GREEN, GREY, RED, GOLD
from bot.formatting import num, truncate
from bot.snapshots import SnapshotReader


def find_member(members, query):
    """Case-insensitive name or tag match, tag without leading '#' allowed."""
    needle = str(query or "").strip().lower().lstrip("#")
    if not needle:
        return None
    for member in members or []:
        name = str(member.get("name") or "").lower()
        tag = str(member.get("tag") or "").lower().lstrip("#")
        if needle == name or needle == tag or needle in name or needle in tag:
            return member
    return None


def build_clan_embed(clan):
    embed = discord.Embed(title=f"🏛️ {clan.get('name', '?')} · overview", color=BLUE)
    if not clan:
        embed.description = "No clan snapshot available."
        return embed
    embed.add_field(name="Clan", value=f"{clan.get('name', '?')} (Lv {clan.get('clanLevel', '?')})", inline=True)
    embed.add_field(name="Points", value=num(clan.get("clanPoints", 0)), inline=True)
    wins = clan.get("warWins") or 0
    losses = clan.get("warLosses") or 0
    embed.add_field(name="War W/L", value=f"{wins}W – {losses}L", inline=True)
    embed.add_field(name="War win streak", value=str(clan.get("warWinStreak") or 0), inline=True)
    embed.add_field(name="Members", value=f"{len(clan.get('memberList') or [])}/50", inline=True)
    capital = clan.get("clanCapital") or {}
    embed.add_field(name="Capital Hall", value=str(capital.get("capitalHallLevel") or 0), inline=True)
    embed.add_field(
        name="Capital league",
        value=str((clan.get("capitalLeague") or {}).get("name") or "—"),
        inline=True,
    )
    embed.set_footer(text="99N War Room · clan")
    return embed


def build_roster_embed(members, role=None, sort_key=None):
    members = members or []
    rows = list(members)
    if role:
        wanted = str(role).lower()
        rows = [m for m in rows if str(m.get("role") or "").lower() == wanted]
    if sort_key:
        rows = sorted(
            rows,
            key=lambda m: (m.get(sort_key) is None, m.get(sort_key) or 0),
            reverse=(sort_key in ("donations", "trophies", "warStars", "builderBaseTrophies")),
        )
    lines = []
    for m in rows[:50]:
        lines.append(
            f"**{m.get('name', '?')}** `{m.get('tag', '')}` — TH{int(m.get('townHallLevel') or 0)}, "
            f"🏆 {num(m.get('trophies', 0))}, 🎁 {num(m.get('donations', 0))} (got {num(m.get('donationsReceived', 0))})"
        )
    embed = discord.Embed(title="👥 Roster", color=GOLD)
    embed.description = truncate("\n".join(lines)) if lines else "No members found."
    embed.add_field(name="Shown", value=str(len(lines)), inline=True)
    return embed


def top_rows(members, metric, limit=10):
    rows = list(members or [])
    rows = sorted(rows, key=lambda m: m.get(metric) or 0, reverse=True)
    return rows[: max(1, limit)]


def inactive_members(members, days=7):
    """Members with zero donations in the last ``days`` snapshots."""
    threshold = int((days or 7) * 1440)
    return [
        m for m in members or []
        if int(m.get("donations") or 0) < threshold
    ]


class ClanCog(commands.Cog, name="clan"):
    def __init__(self, bot):
        self.bot = bot
        self.reader = SnapshotReader(str(bot_config.DATA_DIR))

    @commands.hybrid_command(name="clan", description="Clan overview card")
    async def clan(self, ctx):
        await ctx.send(embed=build_clan_embed(self.reader.clan()))

    @commands.hybrid_command(name="roster", description="Clan roster with filters")
    async def roster(
        self,
        ctx,
        role: str = None,
        sort: str = None,
        limit: int = 50,
    ):
        members = self.reader.members()
        key = {"donations": "donations", "trophies": "trophies"}.get(
            (sort or "").lower(), None
        )
        embed = build_roster_embed(members, role=role, sort_key=key)
        if limit and limit > 50:
            limit = 50
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="top", description="Top N members by a metric")
    async def top(
        self,
        ctx,
        metric: str = "donations",
        limit: int = 10,
    ):
        members = self.reader.members()
        rows = top_rows(members, metric, limit=limit)
        lines = [f"**{i + 1}.** {m.get('name', '?')} — {m.get('tag', '')}" for i, m in enumerate(rows)]
        embed = discord.Embed(title="🏆 Top members", color=GOLD)
        embed.description = truncate("\n".join(lines))
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ClanCog(bot))
