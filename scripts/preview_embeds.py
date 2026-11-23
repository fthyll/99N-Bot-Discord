"""Render every enriched embed from the real snapshot data to a preview file.

Run: python3 scripts/preview_embeds.py [out.md]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import bot_config
from bot.cogs.clan import build_clan_embed, build_roster_embed, top_rows
from bot.cogs.raid import build_raid_embed, build_raid_members_embed
from bot.cogs.war import build_war_embed, build_warstats_embed
from bot.formatting import bar, medal, num, truncate


def flatten(embed):
    """Embed -> lines of text, so a diff shows exactly what Discord renders."""
    out = [f"### {embed.title or '(no title)'}"]
    if embed.description:
        out.append(embed.description)
    for field in embed.fields:
        out.append(f"**{field.name}** — {field.value}")
    if embed.footer.text:
        out.append(f"_footer: {embed.footer.text}_")
    if embed.thumbnail.url:
        out.append(f"_thumbnail: {embed.thumbnail.url}_")
    return "\n".join(out)


def build_top_preview(members, metric, limit=10):
    """Mirror of the /top command's embed, which lives inline in the cog."""
    import discord

    rows = top_rows(members, metric, limit=limit)
    peak = max((int(m.get(metric) or 0) for m in rows), default=0)
    lines = []
    for i, m in enumerate(rows, 1):
        value = int(m.get(metric) or 0)
        lines.append(f"{medal(i)} **{m.get('name', '?')}** — {num(value)}\n`{bar(value, peak)}`")
    embed = discord.Embed(title=f"🏆 Top by {metric}", color=0xF1C40F)
    embed.description = truncate("\n".join(lines)) or "No members found."
    embed.set_footer(text=f"{len(rows)} of {len(members)} members")
    return embed


def main():
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "embed_preview.md")
    reader = bot_config.build_reader()
    clan = reader.clan() or {}
    war = reader.war() or {}
    raid = reader.raid() or {}

    sections = [
        ("/clan", build_clan_embed(clan)),
        ("/roster", build_roster_embed(reader.members())),
        ("/top trophies", build_top_preview(reader.members(), "trophies")),
        ("/raid", build_raid_embed(raid)),
        ("/raid-members", build_raid_members_embed(raid, reader.members())),
    ]
    if war and war.get("state") not in (None, "notInWar"):
        sections += [
            ("/war", build_war_embed(war)),
            ("/warstats", build_warstats_embed([war] if war.get("state") == "warEnded" else [])),
        ]

    text = "\n\n---\n\n".join(flatten(e) for _, e in sections)
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path} ({len(text)} chars, {len(sections)} embeds)")
    print(f"data mode: {'live' if bot_config.COC_API_TOKEN else 'snapshots'}")


if __name__ == "__main__":
    main()
