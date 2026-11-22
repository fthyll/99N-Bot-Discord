"""War commands: status, attack reminders, lineup, war log, war stats."""

import discord
from discord.ext import commands

from bot import bot_config
from bot.embeds import BLUE, GREEN, GREY, RED, GOLD
from bot.formatting import coc_time, duration_text, hours_until, num, truncate
from bot.snapshots import SnapshotReader

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
    lines = [
        f"**State**: {state}",
        f"**Size**: {war.get('teamSize', '?')}v{war.get('teamSize', '?')}",
        f"**Stars**: {clan.get('stars', 0)} – {opponent.get('stars', 0)}",
        f"**Destruction**: {clan.get('destructionPercentage', 0):.1f}% vs "
        f"{opponent.get('destructionPercentage', 0):.1f}%",
        f"**Attacks used**: {clan.get('attacks', 0)} / "
        f"{int(war.get('teamSize') or 0) * int(war.get('attacksPerMember') or 2)}",
    ]
    if remaining is not None:
        lines.append(f"**Ends**: {coc_time(war.get('endTime'))} ({duration_text(remaining)})")
    embed.description = "\n".join(lines)

    embed.add_field(name="Opponent", value=f"{opponent.get('name', '?')} (Lv {opponent.get('clanLevel', '?')})", inline=True)
    embed.add_field(name="Attacks left", value=str(attacks_left(war)), inline=True)
    embed.add_field(name="Modifier", value=str(war.get("battleModifier", "none")).title(), inline=True)
    embed.set_footer(text=f"99N War Room · {coc_time(war.get('startTime'))}")
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
        lines.append(f"**{row['name']}** — {row['attacks']}/{row['max_attacks']} used, {left} left{pos}")
    embed.description = truncate("\n".join(lines))
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
    lines = []
    for item in items[:limit]:
        clan = item.get("clan") or {}
        opponent = item.get("opponent") or {}
        result = str(item.get("result", "?")).upper()
        mark = {"WIN": "🏆", "LOSE": "💀", "DRAW": "🤝"}.get(result, "•")
        lines.append(
            f"{mark} **{clan.get('name', 'Clan')}** vs {opponent.get('name', '?')} — "
            f"{clan.get('stars', 0)}–{opponent.get('stars', 0)} stars "
            f"({coc_time(item.get('endTime'))})"
        )
    embed.description = truncate("\n".join(lines))
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
        f"**Win rate**: {rate:.1f}% ({wins}W / {losses}L / {draws}D)\n"
        f"**Current streak**: {streak} win{'s' if streak != 1 else ''}\n"
        f"**Avg stars**: {ours:.1f} — {theirs:.1f}"
    )
    return embed


class WarCog(commands.Cog, name="war"):
    def __init__(self, bot):
        self.bot = bot
        self.reader = SnapshotReader(str(bot_config.DATA_DIR))

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
