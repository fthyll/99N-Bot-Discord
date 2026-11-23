"""Clan commands: overview card, roster, top, inactive members."""

import discord
from discord.ext import commands

from bot import bot_config
from bot.embeds import BLUE, GREEN, GREY, RED, GOLD
from bot.formatting import bar, medal, num, pct, truncate


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
    embed.description = clan.get("description") or None

    embed.add_field(name="Clan", value=f"{clan.get('name', '?')} (Lv {clan.get('clanLevel', '?')})", inline=True)
    embed.add_field(name="Points", value=num(clan.get("clanPoints", 0)), inline=True)
    wins = clan.get("warWins") or 0
    losses = clan.get("warLosses") or 0
    draws = clan.get("warTies") or 0
    embed.add_field(name="War record", value=f"{wins}W – {losses}L – {draws}D", inline=True)
    embed.add_field(
        name="War win rate",
        value=f"{pct(wins, wins + losses + draws)}\n{bar(wins, wins + losses + draws)}",
        inline=True,
    )
    embed.add_field(name="Win streak", value=f"🔥 {clan.get('warWinStreak') or 0}", inline=True)
    members = clan.get("memberList") or []
    embed.add_field(name="Members", value=f"{len(members)}/50\n{bar(len(members), 50, 10)}", inline=True)
    capital = clan.get("clanCapital") or {}
    embed.add_field(name="Capital Hall", value=str(capital.get("capitalHallLevel") or 0), inline=True)
    embed.add_field(
        name="Capital league",
        value=str((clan.get("capitalLeague") or {}).get("name") or "—"),
        inline=True,
    )

    # War league and location are what people actually ask about, and both are
    # absent from the old card even though the snapshot always carries them.
    league = (clan.get("warLeague") or {}).get("name")
    if league:
        embed.add_field(name="War league", value=str(league), inline=True)
    location = (clan.get("location") or {}).get("name")
    if location:
        embed.add_field(name="Location", value=str(location), inline=True)
    if clan.get("tag"):
        embed.add_field(name="Tag", value=f"`{clan['tag']}`", inline=True)

    labels = [l.get("name") for l in clan.get("labels") or [] if isinstance(l, dict) and l.get("name")]
    if labels:
        embed.add_field(name="Labels", value=" · ".join(labels), inline=False)

    badge = (clan.get("badgeUrls") or {}).get("large") or (clan.get("badgeUrls") or {}).get("medium")
    if badge:
        embed.set_thumbnail(url=badge)

    embed.set_footer(text="99N War Room · clan")
    return embed


def build_roster_embed(members, role=None, sort_key=None, limit=50):
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
    shown = rows[:max(1, min(int(limit or 50), 50))]
    lines = []
    for m in shown:
        role = str(m.get("role") or "member")
        crown = {"leader": "👑 ", "coLeader": "⭐ "}.get(role, "")
        lines.append(
            f"{crown}**{m.get('name', '?')}** `{m.get('tag', '')}` — TH{int(m.get('townHallLevel') or 0)}, "
            f"🏆 {num(m.get('trophies', 0))}, 🎁 {num(m.get('donations', 0))} "
            f"(got {num(m.get('donationsReceived', 0))})"
        )
    embed = discord.Embed(title="👥 Roster", color=GOLD)
    embed.description = truncate("\n".join(lines)) if lines else "No members found."
    embed.add_field(name="Shown", value=f"{len(lines)}/{len(rows)}", inline=True)
    # Donation balance is the number officers actually argue about; the old
    # card listed the two counters without ever combining them.
    given = sum(int(m.get("donations") or 0) for m in shown)
    got = sum(int(m.get("donationsReceived") or 0) for m in shown)
    embed.add_field(name="Donations", value=f"🎁 {num(given)} / received {num(got)}", inline=True)
    embed.add_field(name="Net", value=f"{given - got:+,}", inline=True)
    return embed


METRICS = ("donations", "trophies", "warStars", "builderBaseTrophies", "donationsReceived")
ROLES = ("member", "elder", "coLeader", "leader")


def top_rows(members, metric, limit=10):
    rows = list(members or [])
    rows = sorted(rows, key=lambda m: m.get(metric) or 0, reverse=True)
    return rows[: max(1, limit)]


def inactive_members(members, days=7):
    """Members with zero donations in the newest snapshot.

    ``donations`` is a per-season counter reset every month, not a timestamp,
    so it cannot express "N days idle" — the old ``days * 1440`` threshold
    flagged every member in the clan.
    """
    return [m for m in members or [] if int(m.get("donations") or 0) == 0]


class ClanCog(commands.Cog, name="clan"):
    def __init__(self, bot):
        self.bot = bot
        self.reader = bot_config.build_reader()

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
        if role and str(role).lower() not in ROLES:
            await ctx.send(
                f"❌ Unknown role `{role}`. Pick one of: {', '.join(ROLES)}."
            )
            return
        embed = build_roster_embed(members, role=role, sort_key=key, limit=limit)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="top", description="Top N members by a metric")
    async def top(
        self,
        ctx,
        metric: str = "donations",
        limit: int = 10,
    ):
        if metric not in METRICS:
            await ctx.send(
                f"❌ Unknown metric `{metric}`. Pick one of: {', '.join(METRICS)}."
            )
            return
        members = self.reader.members()
        rows = top_rows(members, metric, limit=limit)
        peak = max((int(m.get(metric) or 0) for m in rows), default=0)
        lines = []
        for i, m in enumerate(rows, 1):
            value = int(m.get(metric) or 0)
            lines.append(
                f"{medal(i)} **{m.get('name', '?')}** — {num(value)}\n"
                f"`{bar(value, peak)}`"
            )
        embed = discord.Embed(title=f"🏆 Top by {metric}", color=GOLD)
        embed.description = truncate("\n".join(lines)) or "No members found."
        embed.set_footer(text=f"{len(rows)} of {len(members)} members")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ClanCog(bot))
