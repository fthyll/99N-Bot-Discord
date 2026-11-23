"""Player commands: profile card with the Town Hall image, leaderboards, trends."""

import discord
from discord.ext import commands

from bot import bot_config
from bot.embeds import GOLD, BLUE, player_card, player_lookup
from bot.formatting import bar, medal, num, pct, truncate


def build_top_embed(rows, metric):
    embed = discord.Embed(title=f"🏆 Top by {metric}", color=GOLD)
    if not rows:
        embed.description = "No data."
        return embed
    lines = []
    for i, m in enumerate(rows, 1):
        lines.append(
            f"**{i}.** {m.get('name', '?')} `{m.get('tag', '')}` — "
            f"TH{int(m.get('townHallLevel') or 0)}, {num(m.get(metric) or 0)}"
        )
    embed.description = truncate("\n".join(lines))
    return embed


def build_trend_embed(member, points, metric="trophies"):
    embed = discord.Embed(title=f"📈 Trend — {member.get('name', '?')}", color=BLUE)
    if not points:
        embed.description = "No trend data for this player."
        return embed
    lines = []
    for point in points[-14:]:
        lines.append(
            f"`{point.get('date', '?')}` — "
            f"🏆 {num(point.get(metric))} · "
            f"🎁 {num(point.get('donations'))} · "
            f"⭐ {num(point.get('warStars'))}"
        )
    embed.description = truncate("\n".join(lines))
    first, last = points[0], points[-1]
    if metric in first and metric in last:
        delta = (last.get(metric) or 0) - (first.get(metric) or 0)
        embed.add_field(name=f"Change in {metric}", value=f"{delta:+,}", inline=True)
    return embed


def build_compare_embed(one, two):
    embed = discord.Embed(title="⚖️ Player comparison", color=BLUE)
    lines = []
    keys = [
        ("townHallLevel", "Town Hall"),
        ("trophies", "Trophies"),
        ("builderBaseTrophies", "Builder Base"),
        ("donations", "Donations"),
        ("donationsReceived", "Received"),
        ("warStars", "War Stars"),
        ("clanCapitalContributions", "Capital"),
    ]
    for key, label in keys:
        a = one.get(key)
        b = two.get(key)
        lines.append(f"**{label}**: {num(a)} vs {num(b)}")
    embed.description = "\n".join(lines)
    embed.add_field(name=one.get("name", "A"), value=one.get("tag", ""), inline=True)
    embed.add_field(name=two.get("name", "B"), value=two.get("tag", ""), inline=True)
    return embed


class PlayerCog(commands.Cog, name="player"):
    def __init__(self, bot):
        self.bot = bot
        self.reader = bot_config.build_reader()

    @commands.hybrid_command(name="member", description="Player profile with Town Hall image")
    async def member(self, ctx, name_or_tag: str):
        members = self.reader.members()
        target = player_lookup(members, name_or_tag)
        if not target:
            await ctx.send(f"❌ No clan member matching `{name_or_tag}`.")
            return
        profiles = self.reader.players()
        profile = profiles.get(target.get("tag")) or {}
        embed, filename = player_card(target, profile)
        path = bot_config.th_asset(target.get("townHallLevel"))
        if path:
            await ctx.send(embed=embed, file=discord.File(path, filename=filename))
        else:
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="th", description="Show a Town Hall image")
    async def th(self, ctx, level: int):
        path = bot_config.th_asset(level)
        if not path:
            await ctx.send(f"❌ No Town Hall asset for level `{level}` (valid: 1–19).")
            return
        embed = discord.Embed(
            title=f"🏰 Town Hall {level}",
            color=GOLD,
        )
        embed.set_image(url=f"attachment://Town_Hall{level}.webp")
        await ctx.send(embed=embed, file=discord.File(path, filename=f"Town_Hall{level}.webp"))

    @commands.hybrid_command(name="topplayers", description="Top players by war stars or capital")
    async def topplayers(self, ctx, metric: str = "warStars", limit: int = 10):
        profiles = self.reader.players()
        rows = sorted(profiles.values(), key=lambda p: p.get(metric) or 0, reverse=True)[:limit]
        peak = max((int(p.get(metric) or 0) for p in rows), default=0)
        embed = discord.Embed(title=f"🏆 Top by {metric}", color=GOLD)
        lines = []
        for i, p in enumerate(rows, 1):
            value = int(p.get(metric) or 0)
            lines.append(
                f"{medal(i)} **{p.get('name', '?')}** `{p.get('tag', '')}` — {num(value)}\n"
                f"`{bar(value, peak)}`"
            )
        embed.description = truncate("\n".join(lines)) or "No data."
        embed.set_footer(text=f"from {len(profiles)} profiles")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="trend", description="Trend of one player over time")
    async def trend(self, ctx, name_or_tag: str, metric: str = "trophies"):
        members = self.reader.members()
        target = player_lookup(members, name_or_tag)
        if not target:
            await ctx.send(f"❌ No clan member matching `{name_or_tag}`.")
            return
        trends = self.reader.trends().get("players") or {}
        points = trends.get(target.get("tag")) or []
        await ctx.send(embed=build_trend_embed(target, points, metric))

    @commands.hybrid_command(name="compare", description="Compare two players")
    async def compare(self, ctx, first: str, second: str):
        members = self.reader.members()
        one = player_lookup(members, first)
        two = player_lookup(members, second)
        if not one or not two:
            await ctx.send("❌ Both names must match a clan member.")
            return
        profiles = self.reader.players()
        await ctx.send(embed=build_compare_embed(
            {**one, **(profiles.get(one.get("tag")) or {})},
            {**two, **(profiles.get(two.get("tag")) or {})},
        ))

    @commands.hybrid_command(name="cwl", description="Clan War League standings")
    async def cwl(self, ctx):
        meta = self.reader.meta()
        clan_name = (self.reader.clan() or {}).get("name")
        cwl = meta.get("cwl")
        embed = discord.Embed(title="🏆 Clan War League", color=GOLD)
        if not isinstance(cwl, dict) or not cwl:
            embed.description = "Not in a season right now."
            await ctx.send(embed=embed)
            return
        embed.description = f"**State**: {cwl.get('state', '—')}\n**Season**: {cwl.get('season') or '—'}"
        standings = cwl.get("standings") or []
        if standings:
            peak = max(
                ((r.get("wins") or 0) * 3 + (r.get("draws") or 0)) for r in standings
            ) or 1
            lines = []
            ours = (clan_name or "").lower()
            for row in standings[:20]:
                points = (row.get("wins") or 0) * 3 + (row.get("draws") or 0)
                flag = "🔸 " if ours and str(row.get("name", "")).lower() == ours else ""
                lines.append(
                    f"{flag}**{row.get('position', '?')}.** {row.get('name', '?')} — "
                    f"{row.get('wins', 0)}W {row.get('draws', 0)}D {row.get('losses', 0)}L "
                    f"({points} pts)\n`{bar(points, peak, 10)}`"
                )
            embed.description += "\n" + truncate("\n".join(lines))
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="inactive", description="Members with no donations")
    async def inactive(self, ctx):
        members = self.reader.members()
        idle = [m for m in members if int(m.get("donations") or 0) == 0]
        embed = discord.Embed(title="💤 Inactive members", color=0x95A5A6)
        if not idle:
            embed.description = "Everyone donated this snapshot."
        else:
            embed.description = truncate("\n".join(f"🔸 **{m.get('name', '?')}**" for m in idle))
            embed.add_field(name="Idle", value=f"{len(idle)}/{len(members)}", inline=True)
            embed.add_field(name="Active", value=pct(len(members) - len(idle), len(members)), inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(PlayerCog(bot))
