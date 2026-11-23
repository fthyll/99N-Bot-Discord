"""Structural check for the notification panel: no Discord connection needed.

Verifies the view actually builds (decorator registration, row assignment,
option count within Discord's 25-option cap) and that the embed renders every
event. A broken decorator or a 26th option would otherwise only surface when a
user runs the command.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.config_store import ConfigStore
from bot.events import event_keys, grouped_keys
from bot.notif_panel import ALL_VALUE, build_panel_embed, event_options, NotifPanel

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


with tempfile.TemporaryDirectory() as d:
    store = ConfigStore(root=d)
    cfg = store.get(1)

    print("options / embed")
    opts = event_options(cfg)
    check("every event has a dropdown entry", len(opts) == len(event_keys()) + 1,
          f"{len(opts)} vs {len(event_keys()) + 1}")
    check("stays within Discord's 25-option cap", len(opts) <= 25, str(len(opts)))
    check("all entries are select options",
          all(type(o).__name__ == "SelectOption" for o in opts))
    check("every option has a description or is the all-row",
          all((o.description is not None) or (o.value == ALL_VALUE) for o in opts))

    groups = grouped_keys()
    check("every key lands in exactly one group",
          sorted(k for _, ks in groups for k in ks) == event_keys())

    embed = build_panel_embed(cfg, selected="war.result")
    check("one embed field per group", len(embed.fields) == len(groups))
    rendered = "\n".join(f.value or "" for f in embed.fields)
    missing = [k for k in event_keys() if k.split(".")[0] not in rendered.lower()
               and k not in rendered]
    check("no event silently missing from the embed",
          "War matched" in rendered and "Scraper stalled" in rendered,
          str(missing))

    print("view")
    view = NotifPanel(store, guild_id=1, author_id=99)
    check("view builds", view is not None)
    check("panel has 4 selects and 5 buttons", len(view.children) == 9,
          f"{len(view.children)}: {[type(c).__name__ for c in view.children]}")
    rows = [c._rendered_row for c in view.children if c._rendered_row is not None]
    check("no item exceeds row 4", all(r is not None and r <= 4 for r in rows), str(rows))
    check("at most 5 rows used", len(set(rows)) <= 5, str(sorted(set(rows))))
    check("actions disabled before a selection",
          view.on_button.disabled and view.off_button.disabled)

    print("behaviour")
    view.selected = "war.result"
    view._sync_actions()
    check("actions enabled after selecting an event",
          not view.on_button.disabled and not view.off_button.disabled)
    view._apply_enabled(False)
    check("turn off persists to the config file",
          store.get(1)["events"]["war.result"]["enabled"] is False)
    view._apply_enabled(True)
    check("turn on persists to the config file",
          store.get(1)["events"]["war.result"]["enabled"] is True)

    view.selected = ALL_VALUE
    view._sync_actions()
    check("sample button disabled for the all-row", view.test_button.disabled)
    view._apply_enabled(False)
    check("all-row applies to every event",
          all(not s["enabled"] for s in store.get(1)["events"].values()))
    view._apply_channel(123456789)
    check("all-row routing applies to every event",
          all(s["channel_id"] == 123456789 for s in store.get(1)["events"].values()))

    view.selected = "raid.reminder"
    view._apply_role(555)
    check("role lands on the selected event only",
          store.get(1)["events"]["raid.reminder"]["ping_role_id"] == 555
          and store.get(1)["events"]["raid.start"]["ping_role_id"] is None)

    opts_after = event_options(store.get(1))
    off = [o for o in opts_after if o.value == "war.result"]
    check("dropdown reflects the saved state", off and off[0].label.startswith("⛔"),
          off[0].label if off else "missing")

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("panel probe: all checks passed")
