"""Render the notification panel to markdown for offline review.

Discord UI cannot be screenshotted from here, so this prints exactly what the
panel message and its dropdown will contain. Same idea as preview_embeds.py:
look at the real text before trusting it in a server.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.config_store import ConfigStore
from bot.events import event_help, event_label
from bot.notif_panel import ALL_VALUE, build_panel_embed, event_options, NotifPanel

OUT = Path(__file__).resolve().parents[1] / "panel_preview.md"


def render_embed(embed, out):
    out.append(f"## {embed.title}")
    if embed.description:
        out.append(embed.description)
    for field in embed.fields:
        out.append(f"\n### {field.name}")
        out.append(field.value or "")
    if embed.footer and embed.footer.text:
        out.append(f"\n_{embed.footer.text}_")


def main():
    with tempfile.TemporaryDirectory() as d:
        store = ConfigStore(root=d)

        # A realistic setup: war pings to one channel with a role, raid left on,
        # a few clan events off. Shows every visual state the panel can render.
        store.set_channel(1, "all", 111222333444555666)
        store.set_role(1, "war.preparation", 999888777666555444)
        store.set(1, "events.clan.donation_weekly.enabled", False)
        store.set(1, "events.clan.inactive.enabled", False)
        store.set(1, "events.war.cleanup.enabled", False)

        cfg = store.get(1)
        out = [
            "# Notification panel preview",
            "",
            "Rendered from a sample config: all events routed to one channel,",
            "a role on `war.preparation`, and three clan/war events switched off.",
            "",
            "---",
            "",
        ]

        render_embed(build_panel_embed(cfg, selected="war.preparation"), out)

        out += ["", "---", "", "## Dropdown contents", "",
                "| # | Label | Value | Description |", "|---|---|---|---|"]
        for i, opt in enumerate(event_options(cfg), 1):
            out.append(f"| {i} | {opt.label} | `{opt.value}` | {opt.description or '—'} |")

        out += ["", "---", "", "## Row layout", "",
                "| Row | Component |", "|---|---|"]
        view = NotifPanel(store, guild_id=1, author_id=1)
        for item in view.children:
            out.append(f"| {item._rendered_row} | {type(item).__name__} |")

        out += ["", "---", "", "## Autocomplete examples", ""]
        out.append("`/notif set event:` typing `reminder` matches:")
        for key in ("war.attack_reminder", "raid.reminder"):
            out.append(f"- `{event_label(key)}` → `{key}` — {event_help(key)}")

        OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"wrote {OUT}")
        print("\n".join(out[:8]))


if __name__ == "__main__":
    main()
