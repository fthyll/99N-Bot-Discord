"""War commands: status, attack reminders, lineup, war log, war stats."""

import discord
from discord.ext import commands

from bot import bot_config
from bot.embeds import BLUE, GREEN, GREY, RED, GOLD
from bot.formatting import bar, coc_time, duration_text, form, hours_until, num, pct, truncate

STATE_COLORS = {
    "preparation": BLUE,
    "inWar": RED,
    "warEnded": GREEN,
}


def attacks_left(war):
    """Attacks still available to the clan."""
    if not war:
        return 0
    team = int(war.get("teamSize") or 0)
    per_member = int(war.get("attacksPerMember") or 2)
    used = int((war.get("clan") or {}).get("attacks") or 0)
    return max(0, team * per_member - used)


def attack_summary(war):
    """One row per attacking member: name, TH, attacks used, best star hit.

    ``member['attacks']`` is the list of attacks *we* made; ``opponentAttacks``
    is how many times the enemy hit that base, so it must never be used as an
    attack counter.
    """
    clan = (war or {}).get("clan") or {}
    per_member = int((war or {}).get("attacksPerMember") or 2)
    rows = []
    for member in clan.get("members") or []:
        made = member.get("attacks") or []
        best = max(made, key=lambda a: (a.get("stars") or 0), default=None) or {}
        rows.append({
            "name": member.get("name", "?"),
            "tag": member.get("tag", ""),
            "th": member.get("townhallLevel"),
            "position": member.get("mapPosition"),
            "attacks": len(made),
            "max_attacks": per_member,
            "stars": best.get("stars"),
            "destruction": best.get("destructionPercentage"),
        })
    rows.sort(key=lambda r: (r["attacks"], r["position"] or 99))
    return rows


def build_lineup(war):
    """Pair our member and the opponent member at each map position."""
    clan = (war or {}).get("clan") or {}
    opponent = (war or {}).get("opponent") or {}
    by_pos = {m.get("mapPosition"): m for m in opponent.get("members") or []}
    rows = []
    for member in clan.get("members") or []:
        pos = member.get("mapPosition")
        foe = by_pos.get(pos) or {}
        rows.append({
            "position": pos,
            "name": member.get("name", "?"),
            "th": member.get("townhallLevel"),
            "opponent_name": foe.get("name"),
            "opponent_th": foe.get("townhallLevel"),
        })
    rows.sort(key=lambda r: (r["position"] is None, r["position"] or 0))
    return rows


def build_war_embed(war):
    embed = discord.Embed(color=BLUE)
    if not war:
        embed.title = "⚔️ No war data"
        embed.description = "No war snapshot has been committed yet."
        return embed

    clan = war.get("clan") or {}
    opponent = war.get("opponent") or {}
    state = war.get("state", "unknown")
    embed.title = f"⚔️ {clan.get('name', 'Clan')} vs {opponent.get('name', '?')}"
    embed.color = STATE_COLORS.get(state, GREY)

    remaining = hours_until(war.get("endTime"))
    self_stars = int(clan.get("stars") or 0)
    foe_stars = int(opponent.get("stars") or 0)
    size = int(war.get("teamSize") or 0)
    max_stars = size * 3 or 1
    per_member = int(war.get("attacksPerMember") or 2)
    total_attacks = size * per_member
    used = int(clan.get("attacks") or 0)

    # Leading/trailing tells the reader who is winning faster than two numbers.
    if self_stars > foe_stars:
        lead = f"🟢 +{self_stars - foe_stars} star(s) ahead"
    elif self_stars < foe_stars:
        lead = f"🔴 {foe_stars - self_stars} star(s) behind"
    else:
        lead = "🟡 dead even"

    lines = [
        f"**State** · {state}   |   **Size** · {size}v{size}",
        f"**Lead** · {lead}",
        "",
        f"**Stars** {self_stars} – {foe_stars}   `{bar(self_stars, max_stars, 12)}`",
        f"**Destruction** {clan.get('destructionPercentage', 0):.1f}% – "
        f"{opponent.get('destructionPercentage', 0):.1f}%",
        "",
        f"**Attacks** {used}/{total_attacks}   `{bar(used, total_attacks, 12)}`",
    ]
    if remaining is not None:
        lines.append(f"**Ends** · {coc_time(war.get('endTime'))} ({duration_text(remaining)})")
    embed.description = "\n".join(lines)

    embed.add_field(name="⚔️ Opponent", value=f"{opponent.get('name', '?')} (Lv {opponent.get('clanLevel', '?')})", inline=True)
    embed.add_field(name="🎯 Attacks left", value=str(attacks_left(war)), inline=True)
    embed.add_field(name="✨ Modifier", value=str(war.get("battleModifier", "none")).title(), inline=True)

    # Attacks still in hand, grouped by how many each member owes. This is the
    # one thing officers check mid-war and the old card never showed it.
    rows = attack_summary(war)
    idle = [r for r in rows if r["attacks"] == 0]
    if rows:
        embed.add_field(name="Members", value=f"{len(rows)} on the map", inline=True)
        embed.add_field(name="No attacks yet", value=f"{len(idle)} member(s)", inline=True)
        avg = used / len(rows) if rows else 0
        embed.add_field(name="Avg attacks", value=f"{avg:.1f}/{per_member}", inline=True)

    for side, field_name in ((clan, "Our badge"), (opponent, "Their badge")):
        badge = (side.get("badgeUrls") or {}).get("medium") or (side.get("badgeUrls") or {}).get("small")
        if badge:
            embed.set_thumbnail(url=badge)
            break

    embed.set_footer(text=f"99N War Room · started {coc_time(war.get('startTime'))}")
    return embed


def build_attack_embed(war):
    """Who has not finished their attacks."""
    rows = attack_summary(war)
    without = [r for r in rows if r["attacks"] < r["max_attacks"]]
    embed = discord.Embed(
        title="🗡️ Attack status",
        color=RED if without else GREEN,
    )
    if not without:
        embed.description = "Every attacker has used all their attacks."
        return embed
    lines = []
    for row in without[:25]:
        left = row["max_attacks"] - row["attacks"]
        pos = f" · pos {row['position']}" if row["position"] is not None else ""
        lines.append(
            f"**{row['name']}** — {left} left{pos}\n"
            f"`{bar(row['attacks'], row['max_attacks'], 4)}` {row['attacks']}/{row['max_attacks']}"
        )
    embed.description = truncate("\n".join(lines))
    embed.add_field(name="⚠️ Still owe", value=str(len(without)), inline=True)
    embed.add_field(name="✅ Finished", value=str(len(rows) - len(without)), inline=True)
    embed.add_field(name="📊 Completion", value=pct(len(rows) - len(without), len(rows)), inline=True)
    embed.set_footer(text=f"{len(without)} of {len(rows)} attackers still have attacks left")
    return embed


def build_lineup_embed(war):
    rows = build_lineup(war)
    embed = discord.Embed(title="🗺️ Lineup by position", color=BLUE)
    if not rows:
        embed.description = "No lineup data in this snapshot."
        return embed
    lines = []
    for row in rows:
        pos = row["position"] if row["position"] is not None else "?"
        foe = "—"
        if row["opponent_name"]:
            foe = f"{row['opponent_name']} (TH{row['opponent_th']})"
        lines.append(f"**{pos}.** {row['name']} (TH{row['th']}) vs {foe}")
    embed.description = truncate("\n".join(lines))
    # Same-TH bases are the easy clean-up targets; a negated edge is the one
    # that needs a plan.
    pairs = [(r["th"], r["opponent_th"]) for r in rows if r["th"] and r["opponent_th"]]
    if pairs:
        even = sum(1 for a, b in pairs if a == b)
        easier = sum(1 for a, b in pairs if a > b)
        harder = sum(1 for a, b in pairs if a < b)
        embed.add_field(name="Matchups", value=f"= {even} · easier {easier} · harder {harder}", inline=True)
    embed.set_footer(text=f"{len(rows)} positions")
    return embed


def build_warlog_embed(items, limit=10):
    """Most recent ``limit`` wars, newest first.
    ``warlog.items`` is newest-first (items[0] is the last war played), so the
    head of the list is what the user wants, not the tail.
    """
    embed = discord.Embed(title="📜 Recent wars", color=GREY)
    if not items:
        embed.description = "No war log available."
        return embed
    shown = items[:limit]
    embed.description = (
        f"**Form** (oldest → newest)\n{form([i.get('result') for i in shown], limit=limit)}"
    )
    lines = []
    for item in shown:
        clan = item.get("clan") or {}
        opponent = item.get("opponent") or {}
        result = str(item.get("result", "?")).upper()
        mark = {"WIN": "🏆", "LOSE": "💀", "DRAW": "🤝"}.get(result, "•")
        lines.append(
            f"{mark} **{clan.get('name', 'Clan')}** vs {opponent.get('name', '?')} — "
            f"{clan.get('stars', 0)}–{opponent.get('stars', 0)} stars "
            f"({coc_time(item.get('endTime'))})"
        )
    embed.add_field(name=f"Last {len(shown)} wars", value=truncate("\n".join(lines)), inline=False)
    return embed


def build_warstats_embed(items):
    """Win rate, streak, average stars over the archived wars."""
    finished = [i for i in items if i.get("result") in ("win", "lose", "draw")]
    embed = discord.Embed(title="📊 War stats", color=GOLD)
    if not finished:
        embed.description = "No finished wars in the archive yet."
        return embed
    wins = sum(1 for i in finished if i.get("result") == "win")
    losses = sum(1 for i in finished if i.get("result") == "lose")
    draws = len(finished) - wins - losses
    rate = wins / len(finished) * 100

    # items are newest-first, so a streak counts from the head of the list.
    streak = 0
    for item in finished:
        if item.get("result") == "win":
            streak += 1
        else:
            break

    ours = sum((i.get("clan") or {}).get("stars", 0) for i in finished) / len(finished)
    theirs = sum((i.get("opponent") or {}).get("stars", 0) for i in finished) / len(finished)

    embed.description = (
        f"**Wars archived**: {len(finished)}\n"
        f"`{bar(wins, len(finished), 16)}` **{rate:.1f}%**\n"
        f"**Record**: {wins}W / {losses}L / {draws}D\n"
        f"**Current streak**: 🔥 {streak} win{'s' if streak != 1 else ''}\n"
        f"**Avg stars**: {ours:.1f} — {theirs:.1f}"
    )
    embed.add_field(name="Recent form", value=form([i.get("result") for i in finished]), inline=False)
    embed.add_field(name="Avg stars", value=f"us {ours:.1f} · them {theirs:.1f}", inline=True)
    embed.add_field(name="Star margin", value=f"{ours - theirs:+.1f}", inline=True)
    return embed


class WarCog(commands.Cog, name="war"):
    def __init__(self, bot):
        self.bot = bot
        self.reader = bot_config.build_reader()

    @commands.hybrid_command(name="war", description="Status of the current or last war")
    async def war(self, ctx):
        embed = build_war_embed(self.reader.war())
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="attacks", description="Who still has attacks left")
    async def attacks(self, ctx):
        await ctx.send(embed=build_attack_embed(self.reader.war()))

    @commands.hybrid_command(name="lineup", description="Lineup by map position")
    async def lineup(self, ctx):
        await ctx.send(embed=build_lineup_embed(self.reader.war()))

    @commands.hybrid_command(name="warlog", description="Recent war results")
    @commands.cooldown(1, 5.0)
    async def warlog(self, ctx, count: int = 10):
        items = self.reader.warlog()
        await ctx.send(embed=build_warlog_embed(items, max(1, min(count, 25))))

    @commands.hybrid_command(name="warstats", description="Win rate, streak and average stars")
    async def warstats(self, ctx):
        await ctx.send(embed=build_warstats_embed(self.reader.warlog()))


async def setup(bot):
    await bot.add_cog(WarCog(bot))
