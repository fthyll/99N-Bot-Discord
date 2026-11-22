"""Notification event registry.

One entry per Discord event the bot can send. Every ``trigger`` is a pure
function of ``(ctx, prev)`` returning a list of embeds — empty means nothing to
send this tick. The dispatcher owns the state file, so triggers never mutate
anything and are cheap to unit-test.

The embed builders that used to be imported from the 99N scraper checkout are
vendored in ``bot/notifier_embeds.py`` (zero imports, 5 KB), so this repo has no
filesystem dependency on a sibling checkout. The inline fallbacks remain for
payloads the vendored builders do not cover.
"""

import discord

from bot import embeds as bot_embeds
from bot import formatting as fmt
from bot import notifier_embeds as scraper_embeds
from bot.cogs.raid import raid_member_rows
from bot.cogs.war import attack_summary, attacks_left


def _simple(title, description, color):
    embed = discord.Embed(title=title, description=fmt.truncate(description), color=color)
    embed.set_footer(text="99N War Room · notification")
    return embed


def _reuse(builder, payload):
    """Convert a scraper embed dict; returns [] when the scraper is absent."""
    if scraper_embeds is None:
        return []
    fn = getattr(scraper_embeds, builder, None)
    if fn is None:
        return []
    try:
        if isinstance(payload, tuple):
            raw = fn(*payload)
        else:
            raw = fn(payload)
    except Exception:
        return []
    return [bot_embeds.dict_to_embed(raw)]


# -- fallbacks -------------------------------------------------------------
# The scraper package is optional (the bot runs from a checkout that may not
# have it). Without these, five events would silently produce nothing at all.

def _war_preview_fallback(war):
    clan = war.get("clan") or {}
    opponent = war.get("opponent") or {}
    return _simple(
        "⚔️ War matched",
        f"**{clan.get('name', 'Clan')}** vs **{opponent.get('name', '?')}**\n"
        f"Size: {war.get('teamSize', '?')}v{war.get('teamSize', '?')}\n"
        f"Starts {fmt.coc_time(war.get('startTime'))}",
        0x5865F2,
    )


def _war_result_fallback(war):
    clan = war.get("clan") or {}
    opponent = war.get("opponent") or {}
    ours = (clan.get("stars") or 0, clan.get("destructionPercentage") or 0)
    theirs = (opponent.get("stars") or 0, opponent.get("destructionPercentage") or 0)
    if ours > theirs:
        title, color = "🏆 War won", 0x3BA55D
    elif ours < theirs:
        title, color = "💀 War lost", 0xED4245
    else:
        title, color = "🤝 War drawn", 0x95A5A6
    return _simple(
        title,
        f"**{clan.get('name', 'Clan')}** {ours[0]}★ {ours[1]:.1f}% "
        f"vs **{opponent.get('name', '?')}** {theirs[0]}★ {theirs[1]:.1f}%\n"
        f"Attacks: {clan.get('attacks', 0)} vs {opponent.get('attacks', 0)}",
        color,
    )


def _raid_start_fallback(raid):
    return _simple(
        "🏰 Raid weekend started",
        f"Ends {fmt.coc_time(raid.get('endTime'))}.\n"
        f"{len(raid.get('members') or [])} members are already raiding.",
        0xF5B942,
    )


def _raid_summary_fallback(raid):
    return _simple(
        "🏰 Raid weekend finished",
        f"**Capital loot**: {fmt.num(raid.get('capitalTotalLoot', 0))}\n"
        f"**Districts destroyed**: {raid.get('enemyDistrictsDestroyed', 0)}\n"
        f"**Attacks**: {fmt.num(raid.get('totalAttacks', 0))}",
        0xF5B942,
    )


def _membership_fallback(joined, left, total):
    lines = []
    if joined:
        lines.append("**Joined:** " + ", ".join(joined))
    if left:
        lines.append("**Left:** " + ", ".join(left))
    return _simple(
        "👥 Roster changed",
        "\n".join(lines) + f"\nNow **{total}/50** members.",
        0x5865F2,
    )


def _donation_reset_fallback(before, totals, top):
    delta = (totals.get("donations") or 0) - (before.get("total") or 0)
    lines = [
        f"{i + 1}. **{m.get('name', '?')}** — {fmt.num(m.get('donations', 0))}"
        for i, m in enumerate(top)
    ] or ["—"]
    return _simple(
        "🎁 Donation season reset",
        f"Last season the clan donated **{fmt.num(before.get('total', 0))}** "
        f"(received {fmt.num(before.get('received', 0))}).\n"
        f"A new season starts now ({delta:+,} vs last close).\n" + "\n".join(lines),
        0x3BA55D,
    )


def _war_preparation(ctx, prev):
    war = ctx["war"]
    if war.get("state") != "preparation":
        return []
    if prev.get("war", {}).get("preparation_key") == war.get("startTime"):
        return []
    return _reuse("war_preview", war) or [_war_preview_fallback(war)]


def _war_result(ctx, prev):
    war = ctx["war"]
    if war.get("state") != "warEnded":
        return []
    marker = prev.get("war", {})
    if marker.get("state") == "warEnded" and marker.get("key") == war.get("startTime"):
        return []
    return _reuse("war_result", war) or [_war_result_fallback(war)]


def _war_ending_soon(ctx, prev):
    war = ctx["war"]
    if war.get("state") != "inWar":
        return []
    hours = fmt.hours_until(war.get("endTime"), now=ctx["now"])
    if hours is None or hours > 2:
        return []
    left = attacks_left(war)
    if left == 0 or prev.get("war", {}).get("ending_soon_key") == war.get("startTime"):
        return []
    return [_simple(
        "⚔️ War ending soon",
        f"**{left}** attacks still unused.\n"
        f"War ends {fmt.coc_time(war.get('endTime'))} ({fmt.duration_text(hours)}).",
        0xED4245,
    )]


def _war_attack_reminder(ctx, prev):
    war = ctx["war"]
    if war.get("state") != "inWar":
        return []
    hours = fmt.hours_until(war.get("endTime"), now=ctx["now"])
    if hours is None or hours > 12:
        return []
    pending = [r for r in attack_summary(war) if r["attacks"] < r["max_attacks"]]
    if not pending or prev.get("war", {}).get("reminder_key") == war.get("startTime"):
        return []
    lines = [f"**{r['name']}** — {r['attacks']}/{r['max_attacks']}" for r in pending[:20]]
    return [_simple(
        "🗡️ Attack reminder",
        f"{len(pending)} members still have attacks left "
        f"({fmt.duration_text(hours)} remaining):\n" + "\n".join(lines),
        0xED4245,
    )]


def _war_cleanup(ctx, prev):
    war = ctx["war"]
    if war.get("state") != "warEnded":
        return []
    pending = [r for r in attack_summary(war) if r["attacks"] < r["max_attacks"]]
    if not pending or prev.get("war", {}).get("cleanup_key") == war.get("startTime"):
        return []
    lines = [f"**{r['name']}** — {r['attacks']}/{r['max_attacks']}" for r in pending[:20]]
    return [_simple(
        "🧹 Cleanup needed",
        f"{len(pending)} members did not use all their attacks:\n" + "\n".join(lines),
        0x95A5A6,
    )]


def _raid_start(ctx, prev):
    raid = ctx["raid"]
    if raid.get("state") == "ongoing" and prev.get("raid", {}).get("state") != "ongoing":
        return _reuse("raid_start", raid) or [_raid_start_fallback(raid)]
    return []


def _raid_summary(ctx, prev):
    raid = ctx["raid"]
    if raid.get("state") == "ended" and prev.get("raid", {}).get("state") != "ended":
        return _reuse("raid_summary", raid) or [_raid_summary_fallback(raid)]
    return []


def _raid_reminder(ctx, prev):
    raid = ctx["raid"]
    if raid.get("state") != "ongoing":
        return []
    hours = fmt.hours_until(raid.get("endTime"), now=ctx["now"])
    if hours is None or hours > 12:
        return []
    idle = [r for r in raid_member_rows(raid) if r["attacks"] == 0]
    if not idle or prev.get("raid", {}).get("reminder_key") == raid.get("startTime"):
        return []
    lines = [f"**{r['name']}**" for r in idle[:20]]
    return [_simple(
        "🏰 Raid reminder",
        f"{len(idle)} members have not raided yet "
        f"({fmt.duration_text(hours)} remaining):\n" + "\n".join(lines),
        0xED4245,
    )]


def _clan_roster(ctx, prev):
    clan = ctx["clan"]
    members = {m.get("tag"): m for m in (clan.get("memberList") or []) if m.get("tag")}
    previous = set(prev.get("clan", {}).get("memberTags") or [])
    if not previous:
        return []  # first observation is not a change
    joined = [members[t].get("name") for t in members if t not in previous]
    left = sorted(previous - set(members))
    if not (joined or left):
        return []
    return _reuse("membership_change", (joined, left, len(members))) or [
        _membership_fallback(joined, left, len(members))
    ]


def _clan_donation_reset(ctx, prev):
    clan = ctx["clan"]
    members = {m.get("tag"): m for m in (clan.get("memberList") or []) if m.get("tag")}
    totals = {
        "donations": sum((m.get("donations") or 0) for m in members.values()),
        "received": sum((m.get("donationsReceived") or 0) for m in members.values()),
    }
    before = prev.get("clan", {}).get("donations")
    if not before or not before.get("total"):
        return []
    stamp = ctx["now"].strftime("%Y%m%d")
    if prev.get("clan", {}).get("donation_reset") == stamp:
        return []
    # Counters reset when the league season rolls over: the total collapses.
    if totals["donations"] >= before["total"] * 0.5:
        return []
    top = sorted(members.values(), key=lambda m: m.get("donations") or 0, reverse=True)[:3]
    return _reuse("donation_reset", (before, totals, top)) or [
        _donation_reset_fallback(before, totals, top)
    ]


def _clan_donation_weekly(ctx, prev):
    now = ctx["now"]
    # Monday, 05:00 UTC is when the CoC league week rolls over. The marker is
    # what keeps this to one message; the hour alone spans 60 minutes of ticks.
    if not (now.weekday() == 0 and now.hour == 5):
        return []
    stamp = now.strftime("%Y%m%d")
    if prev.get("clan", {}).get("donation_weekly") == stamp:
        return []
    members = sorted(
        ctx["clan"].get("memberList") or [],
        key=lambda m: m.get("donations") or 0,
        reverse=True,
    )[:5]
    lines = [f"{i + 1}. **{m.get('name', '?')}** — {fmt.num(m.get('donations', 0))}" for i, m in enumerate(members)]
    return [_simple("🎁 Weekly donation leaders", "\n".join(lines) or "—", 0x3BA55D)]


def _clan_inactive(ctx, prev):
    # The marker is written only when the message is delivered, so the guard is
    # a plain "already told them today" check, not a state-shape guess.
    stamp = ctx["now"].strftime("%Y%m%d")
    if prev.get("clan", {}).get("inactive") == stamp:
        return []
    idle = [m for m in ctx["clan"].get("memberList") or [] if int(m.get("donations") or 0) == 0]
    if not idle:
        return []
    lines = [f"**{m.get('name', '?')}**" for m in idle[:20]]
    return [_simple(
        "💤 Inactive members",
        f"{len(idle)} members have 0 donations this snapshot:\n" + "\n".join(lines),
        0x95A5A6,
    )]


def _cwl_round(ctx, prev):
    cwl = (ctx["meta"] or {}).get("cwl")
    if not isinstance(cwl, dict) or not cwl:
        return []
    state = cwl.get("state")
    if state == prev.get("cwl", {}).get("state"):
        return []
    return [_simple(
        "🏆 CWL update",
        f"State: **{state}**\nSeason: {cwl.get('season') or '—'}",
        0xF5B942,
    )]


def _system_stale(ctx, prev):
    reader = ctx.get("reader")
    if reader is None:
        return []
    age = reader.age_hours(reader.freshest_stamp(), now=ctx["now"])
    if age is None or age <= 24:
        return []
    stamp = ctx["now"].strftime("%Y%m%d%H")
    if prev.get("system", {}).get("stale") == stamp:
        return []
    return [_simple(
        "⚠️ 99N scrapers look stalled",
        f"The dashboard is serving stale data.\n- no data written for {age:.1f}h (limit 24h)",
        0xED4245,
    )]


NOTIFY_EVENTS = {
    "war.preparation": _war_preparation,
    "war.result": _war_result,
    "war.ending_soon": _war_ending_soon,
    "war.attack_reminder": _war_attack_reminder,
    "war.cleanup": _war_cleanup,
    "raid.start": _raid_start,
    "raid.summary": _raid_summary,
    "raid.reminder": _raid_reminder,
    "clan.roster": _clan_roster,
    "clan.donation_reset": _clan_donation_reset,
    "clan.donation_weekly": _clan_donation_weekly,
    "clan.inactive": _clan_inactive,
    "cwl.round": _cwl_round,
    "system.stale": _system_stale,
}

GROUP_LABELS = {
    "war": "War",
    "raid": "Raid",
    "clan": "Clan",
    "cwl": "CWL",
    "system": "System",
}


def event_keys():
    return sorted(NOTIFY_EVENTS)


def group_of(key):
    return key.split(".")[0]
