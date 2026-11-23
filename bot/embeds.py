"""Discord embed builders.

The notification shapes already exist in the scraper package
(``scrapers/notifier/embeds.py``) as plain dicts, built for a webhook. This
module converts those dicts into ``discord.Embed`` objects so the bot and the
webhook notifier show the same card, and adds the player card that carries a
Town Hall image as a local attachment.
"""

import discord

GOLD = 0xF5B942
GREEN = 0x3BA55D
RED = 0xED4245
BLUE = 0x5865F2
GREY = 0x95A5A6


def dict_to_embed(payload):
    """Convert a webhook-style embed dict into a discord.Embed."""
    payload = payload or {}
    embed = discord.Embed(
        title=payload.get("title") or None,
        description=payload.get("description") or None,
        color=payload.get("color", BLUE),
    )
    for field in payload.get("fields") or []:
        embed.add_field(
            name=field.get("name", ""),
            value=str(field.get("value", "")),
            inline=bool(field.get("inline", True)),
        )
    footer = payload.get("footer")
    if isinstance(footer, dict) and footer.get("text"):
        embed.set_footer(text=footer["text"])
    if payload.get("image"):
        embed.set_image(url=payload["image"])
    return embed


def player_lookup(members, query):
    """Find one member by name or tag, case-insensitive.

    The leading '#' on a tag is optional in the query, because clan members
    type their tag without it most of the time.
    """
    if not query:
        return None
    needle = str(query).strip().lower().lstrip("#")
    if not needle:
        return None
    for member in members or []:
        name = str(member.get("name", "")).lower()
        tag = str(member.get("tag", "")).lower().lstrip("#")
        if needle == name or needle == tag or needle in name or needle in tag:
            return member
    return None


def player_card(member, profile=None):
    """Player profile card + the asset filename that carries the picture.

    Returns (embed, filename). The filename is the attachment name, so the
    embed thumbnail points at ``attachment://<filename>``.
    """
    member = member or {}
    profile = profile or {}
    th = member.get("townHallLevel") or profile.get("townHallLevel") or 1
    try:
        th = int(th)
    except (TypeError, ValueError):
        th = 1
    th = max(1, min(19, th))
    filename = f"Town_Hall{th}.webp"

    trophies = profile.get("trophies", member.get("trophies"))
    best_trophies = profile.get("bestTrophies")
    donations = profile.get("donations", member.get("donations"))
    received = profile.get("donationsReceived", member.get("donationsReceived"))
    war_stars = profile.get("warStars")
    capital = profile.get("clanCapitalContributions")
    builder = profile.get("builderBaseTrophies", member.get("builderBaseTrophies"))

    role = str(member.get("role", "member"))
    role_mark = {"leader": "👑 ", "coLeader": "⭐ ", "elder": "🔹 "}.get(role, "")
    level = profile.get("expLevel", member.get("expLevel"))

    embed = discord.Embed(
        title=f"🛡️ {member.get('name', 'Unknown')}",
        description=f"**Tag** `{member.get('tag', '—')}`" + (f"  ·  **Lv** {level}" if level else ""),
        color=GOLD,
    )
    embed.add_field(name="Town Hall", value=f"🏰 {th}", inline=True)
    embed.add_field(name="Role", value=f"{role_mark}{role.title()}", inline=True)
    embed.add_field(name="League", value=str((member.get("league") or {}).get("name", "—")), inline=True)
    if trophies is not None:
        value = f"🏆 {trophies:,}"
        if best_trophies:
            value += f"\n-# best {best_trophies:,}"
        embed.add_field(name="Trophies", value=value, inline=True)
    if builder is not None:
        embed.add_field(name="Builder Base", value=f"🏠 {builder:,}", inline=True)
    if donations is not None or received is not None:
        net = (donations or 0) - (received or 0)
        embed.add_field(
            name="Donations",
            value=f"➕ {donations or 0:,} / ➖ {received or 0:,}\n-# net {net:+,}",
            inline=True,
        )
    if war_stars is not None:
        embed.add_field(name="War Stars", value=f"⭐ {war_stars:,}", inline=True)
    if capital is not None:
        embed.add_field(name="Capital", value=f"🏛 {capital:,}", inline=True)

    # Everything the profile endpoint carries beyond the card's headline stats.
    # Absent in snapshot mode, so each is added only when present.
    extra = (
        ("clanRank", "Clan rank"),
        ("previousClanRank", "Previous rank"),
        ("attackWins", "Attack wins"),
        ("defenseWins", "Defense wins"),
        ("donationsReceived", "Received"),
    )
    for key, label in extra:
        value = profile.get(key, member.get(key))
        if value is not None:
            embed.add_field(name=label, value=str(value), inline=True)

    league_tier = (profile.get("leagueTier") or {}).get("name")
    if league_tier:
        embed.add_field(name="League tier", value=str(league_tier), inline=True)

    embed.set_thumbnail(url=f"attachment://{filename}")
    embed.set_footer(text="99N War Room · player profile")
    return embed, filename
