"""Tests for the interactive notification panel and its helpers.

The panel calls Discord's UI API, which cannot be exercised without a gateway
connection. What can be checked is everything that would break at runtime
before a human ever sees it: the view must build with the decorator-registered
items on valid rows, dropdowns must stay inside Discord's 25-option cap, the
panel embed must list every event, and every button must write through to the
config file rather than to an in-memory copy.
"""

import asyncio
import tempfile
import unittest

import discord

from bot.config_store import ConfigStore
from bot.cogs.admin import PRESETS, event_autocomplete
from bot.events import (
    EVENT_HELP,
    EVENT_LABELS,
    event_help,
    event_keys,
    event_label,
    grouped_keys,
)
from bot.notif_panel import (
    ALL_VALUE,
    NotifPanel,
    build_panel_embed,
    event_options,
    event_status,
)


class TestEventMetadata(unittest.TestCase):
    def test_every_event_has_a_label(self):
        for key in event_keys():
            self.assertIn(key, EVENT_LABELS, key)
            self.assertNotEqual(event_label(key), key, f"{key} has no human label")

    def test_every_event_has_help_text(self):
        for key in event_keys():
            self.assertTrue(event_help(key), f"{key} has no help text")
            self.assertLessEqual(len(EVENT_HELP[key]), 100)

    def test_labels_stay_inside_discord_limits(self):
        for key in event_keys():
            # SelectOption label caps at 100 characters.
            self.assertLessEqual(len(event_label(key)) + 3, 100, key)

    def test_grouped_keys_covers_every_event_exactly_once(self):
        flat = [k for _, keys in grouped_keys() for k in keys]
        self.assertEqual(sorted(flat), event_keys())


class TestPanelOptions(unittest.TestCase):
    def _config(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return ConfigStore(root=d.name)

    def test_options_fit_discord_cap(self):
        store = self._config()
        opts = event_options(store.get(1))
        self.assertLessEqual(len(opts), 25)
        self.assertEqual(len(opts), len(event_keys()) + 1)

    def test_options_reflect_saved_state(self):
        store = self._config()
        store.set(1, "events.war.result.enabled", False)
        opts = {o.value: o for o in event_options(store.get(1))}
        self.assertTrue(opts["war.result"].label.startswith("⛔"))
        self.assertTrue(opts["war.preparation"].label.startswith("✅"))

    def test_options_can_exclude_the_wildcard(self):
        store = self._config()
        opts = event_options(store.get(1), include_all=False)
        self.assertNotIn(ALL_VALUE, [o.value for o in opts])
        self.assertEqual(len(opts), len(event_keys()))

    def test_every_option_has_a_description(self):
        store = self._config()
        for opt in event_options(store.get(1)):
            self.assertTrue(opt.description, opt.value)

    def test_event_status_is_tolerate_of_partial_config(self):
        enabled, channel, role = event_status({}, "war.result")
        self.assertFalse(enabled)
        self.assertIsNone(channel)
        self.assertIsNone(role)


class TestPanelEmbed(unittest.TestCase):
    def _config(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return ConfigStore(root=d.name)

    def test_one_field_per_group(self):
        embed = build_panel_embed(self._config().get(1))
        self.assertEqual(len(embed.fields), len(grouped_keys()))

    def test_every_label_appears(self):
        embed = build_panel_embed(self._config().get(1))
        rendered = "\n".join(f.value or "" for f in embed.fields)
        for key in event_keys():
            self.assertIn(event_label(key), rendered, key)

    def test_missing_channel_is_visible_not_blank(self):
        embed = build_panel_embed(self._config().get(1))
        rendered = "\n".join(f.value or "" for f in embed.fields)
        self.assertIn("no channel yet", rendered)

    def test_selection_is_marked(self):
        embed = build_panel_embed(self._config().get(1), selected="war.result")
        rendered = "\n".join(f.value or "" for f in embed.fields)
        self.assertIn("▶", rendered)
        self.assertIn("War result", embed.footer.text)


class TestPanelView(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.store = ConfigStore(root=d.name)

    def _view(self):
        return NotifPanel(self.store, guild_id=1, author_id=99)

    def test_view_builds_with_all_items(self):
        view = self._view()
        kinds = [type(c) for c in view.children]
        names = [k.__name__ for k in kinds]
        # on/off/sample, quiet, reset, close
        self.assertEqual(names.count("Button"), 6, names)

    def test_pickers_are_real_channel_and_role_selects(self):
        # @ui.select defaults to a plain Select, which renders as an empty
        # dropdown with no options — the pickers silently did nothing until
        # cls= was passed. This asserts the resolved class, not the annotation.
        view = self._view()
        types_ = {type(c) for c in view.children}
        self.assertIn(discord.ui.ChannelSelect, types_)
        self.assertIn(discord.ui.RoleSelect, types_)
        self.assertIn(discord.ui.Select, types_)

    def test_channel_picker_is_limited_to_text_channels(self):
        view = self._view()
        picker = next(c for c in view.children if isinstance(c, discord.ui.ChannelSelect))
        self.assertIn(discord.ChannelType.text, picker.channel_types)
        self.assertNotIn(discord.ChannelType.voice, picker.channel_types)

    def test_pickers_are_disabled_until_something_is_selected(self):
        # An enabled picker with no target can only fail after the user already
        # made a choice. Disabling it up front states the dependency.
        view = self._view()
        self.assertTrue(view.channel_select.disabled)
        self.assertTrue(view.role_select.disabled)
        view.selected = "war.result"
        view._sync_actions()
        self.assertFalse(view.channel_select.disabled)
        self.assertFalse(view.role_select.disabled)

    def test_every_item_sits_on_a_valid_row(self):
        view = self._view()
        for item in view.children:
            self.assertIsNotNone(item._rendered_row, type(item).__name__)
            self.assertLessEqual(item._rendered_row, 4)

    def test_items_fit_in_five_rows(self):
        view = self._view()
        rows = {item._rendered_row for item in view.children}
        self.assertLessEqual(len(rows), 5)

    def test_actions_need_a_selection_first(self):
        view = self._view()
        self.assertTrue(view.on_button.disabled)
        self.assertTrue(view.off_button.disabled)
        self.assertTrue(view.test_button.disabled)
        view.selected = "war.result"
        view._sync_actions()
        self.assertFalse(view.on_button.disabled)
        self.assertFalse(view.off_button.disabled)
        self.assertFalse(view.test_button.disabled)

    def test_sample_button_disabled_for_wildcard(self):
        view = self._view()
        view.selected = ALL_VALUE
        view._sync_actions()
        self.assertTrue(view.test_button.disabled)

    def test_toggle_writes_to_the_config_file(self):
        view = self._view()
        view.selected = "war.result"
        view._apply_enabled(False)
        self.assertFalse(self.store.get(1)["events"]["war.result"]["enabled"])
        view._apply_enabled(True)
        self.assertTrue(self.store.get(1)["events"]["war.result"]["enabled"])

    def test_toggle_leaves_other_events_alone(self):
        view = self._view()
        view.selected = "war.result"
        view._apply_enabled(False)
        self.assertTrue(self.store.get(1)["events"]["raid.start"]["enabled"])

    def test_wildcard_applies_to_every_event(self):
        view = self._view()
        view.selected = ALL_VALUE
        view._apply_enabled(False)
        self.assertTrue(all(not s["enabled"] for s in self.store.get(1)["events"].values()))

    def test_wildcard_channel_uses_configstore_spelling(self):
        # The menu spells the wildcard '__all__'; ConfigStore expects 'all'.
        # Getting this wrong raised KeyError the moment a user picked a channel.
        view = self._view()
        view.selected = ALL_VALUE
        view._apply_channel(123)
        self.assertTrue(all(s["channel_id"] == 123 for s in self.store.get(1)["events"].values()))

    def test_channel_applies_only_to_the_selection(self):
        view = self._view()
        view.selected = "raid.reminder"
        view._apply_channel(777)
        cfg = self.store.get(1)
        self.assertEqual(cfg["events"]["raid.reminder"]["channel_id"], 777)
        self.assertIsNone(cfg["events"]["raid.start"]["channel_id"])

    def test_role_applies_only_to_the_selection(self):
        view = self._view()
        view.selected = "raid.reminder"
        view._apply_role(555)
        cfg = self.store.get(1)
        self.assertEqual(cfg["events"]["raid.reminder"]["ping_role_id"], 555)
        self.assertIsNone(cfg["events"]["raid.start"]["ping_role_id"])

    def test_closed_view_stops_listening(self):
        # stop() is a no-op until the view is actually waiting on interactions,
        # which is why this drives wait() rather than calling stop() bare.
        async def scenario():
            view = self._view()
            task = asyncio.create_task(view.wait())
            await asyncio.sleep(0)
            view.stop()
            await task
            return view

        view = asyncio.run(scenario())
        self.assertTrue(view.is_finished())


class TestAutocomplete(unittest.TestCase):
    def _run(self, current, **kwargs):
        return asyncio.run(event_autocomplete(None, current, **kwargs))

    def test_empty_query_offers_the_wildcard_and_events(self):
        choices = self._run("")
        values = [c.value for c in choices]
        self.assertIn("all", values)
        self.assertEqual(len(values), len(event_keys()) + 1)

    def test_matches_words_inside_the_label(self):
        values = [c.value for c in self._run("reminder")]
        self.assertIn("war.attack_reminder", values)
        self.assertIn("raid.reminder", values)

    def test_matches_the_dotted_key(self):
        self.assertIn("clan.roster", [c.value for c in self._run("clan.ro")])

    def test_is_case_insensitive(self):
        self.assertIn("war.result", [c.value for c in self._run("WAR RESULT")])

    def test_wildcard_can_be_withheld(self):
        values = [c.value for c in self._run("", include_all=False)]
        self.assertNotIn("all", values)

    def test_every_choice_name_fits_discords_limit(self):
        for choice in self._run(""):
            self.assertLessEqual(len(choice.name), 100, choice.value)

    def test_unknown_query_returns_nothing(self):
        self.assertEqual(self._run("zzzznotathing"), [])


class TestPresets(unittest.TestCase):
    def test_every_preset_names_real_events(self):
        valid = set(event_keys())
        for name, spec in PRESETS.items():
            self.assertTrue(spec["keys"], name)
            self.assertTrue(set(spec["keys"]) <= valid, name)

    def test_presets_have_labels_and_descriptions(self):
        for name, spec in PRESETS.items():
            self.assertTrue(spec["label"], name)
            self.assertTrue(spec["description"], name)

    def test_essential_preset_is_a_subset(self):
        self.assertLess(len(PRESETS["essential"]["keys"]), len(event_keys()))

    def test_war_and_raid_presets_are_scoped(self):
        self.assertTrue(all(k.startswith("war.") for k in PRESETS["war-only"]["keys"]))
        self.assertTrue(all(k.startswith("raid.") for k in PRESETS["raid-only"]["keys"]))


if __name__ == "__main__":
    unittest.main()
