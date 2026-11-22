"""Multi-tick notification behaviour.

Every bug in the original notifier was invisible to single-tick tests: the
markers were written on every tick, so the *second* tick was where events
disappeared or repeated. These tests drive the real tick loop.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from bot.config_store import ConfigStore
from bot.notifier import (
    Dispatcher,
    StateStore,
    build_context,
    due_events,
    next_state,
)
from bot.snapshots import SnapshotReader


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, embed=None):
        self.sent.append((content, embed))


class FakeBot:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id):
        return self.channel if channel_id else None


class TestMultiTick(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, "data")
        self.cfg_dir = os.path.join(self.tmp.name, "cfg")
        for folder in ("war_stats", "clan_stats", "raid_stats"):
            os.makedirs(os.path.join(self.data, folder), exist_ok=True)

        self.reader = SnapshotReader(self.data)
        self.config = ConfigStore(root=self.cfg_dir)
        self.config.set(1, "quiet_hours.enabled", False)
        self.config.set_channel(1, "all", 42)

    # -- fixtures ---------------------------------------------------------
    def _war(self, hours_left, attacks_used, members=None, key="W1"):
        end = datetime.now(timezone.utc) + timedelta(hours=hours_left)
        members = members if members is not None else [
            {"tag": "#A", "name": "Alpha", "townhallLevel": 18, "mapPosition": 1,
             "attacks": [{}] * attacks_used, "opponentAttacks": 2},
        ]
        war = {
            "state": "inWar",
            "startTime": key,
            "endTime": end.strftime("%Y%m%dT%H%M%S.000Z"),
            "teamSize": 15,
            "attacksPerMember": 2,
            "clan": {"name": "99N", "stars": 0, "destructionPercentage": 0.0,
                     "attacks": sum(len(m.get("attacks") or []) for m in members),
                     "members": members},
            "opponent": {"name": "Foe", "stars": 0, "destructionPercentage": 0.0,
                         "attacks": 0, "members": []},
        }
        self._write("war_stats", "war_1.json", ["war_1.json"], war)
        return war

    def _clan(self, donations):
        members = [{"tag": f"#M{i}", "name": f"M{i}", "donations": value}
                   for i, value in enumerate(donations)]
        self._write("clan_stats", "members_1.json", ["members_1.json"],
                    {"memberList": members})

    def _write(self, folder, filename, index, payload):
        with open(os.path.join(self.data, f"{folder}_index.json"), "w") as f:
            json.dump(index, f)
        with open(os.path.join(self.data, folder, filename), "w") as f:
            json.dump(payload, f)

    def _tick(self, state, now):
        ctx = build_context(self.reader, state, now=now)
        fired = [key for key, _ in due_events(1, self.config, self.reader, state, now=now)]
        return fired, next_state(ctx, state, fired=fired)

    # -- the regression this whole file exists for ------------------------
    def test_war_warnings_survive_an_early_observation(self):
        """Observing a war with 20h left must not consume the 2h warning."""
        now = datetime.now(timezone.utc)
        self._war(hours_left=20, attacks_used=1)
        fired_early, state = self._tick({}, now)
        self.assertNotIn("war.ending_soon", fired_early)
        self.assertNotIn("war.attack_reminder", fired_early)

        # Same war, now inside both windows.
        self._war(hours_left=1, attacks_used=1)
        fired_late, _ = self._tick(state, now)
        self.assertIn("war.ending_soon", fired_late)
        self.assertIn("war.attack_reminder", fired_late)

    def test_each_war_warning_fires_exactly_once(self):
        now = datetime.now(timezone.utc)
        self._war(hours_left=1, attacks_used=1)
        fired1, state = self._tick({}, now)
        self.assertIn("war.ending_soon", fired1)
        fired2, state = self._tick(state, now)
        self.assertNotIn("war.ending_soon", fired2)
        self.assertNotIn("war.attack_reminder", fired2)

    def test_preparation_announces_every_new_war(self):
        now = datetime.now(timezone.utc)
        for key in ("W1", "W2", "W3"):
            self._write("war_stats", "war_1.json", ["war_1.json"], {
                "state": "preparation", "startTime": key, "teamSize": 15,
                "attacksPerMember": 2, "clan": {"name": "99N", "members": []},
                "opponent": {"name": "Foe", "members": []},
            })
            fired, state = self._tick(state if key != "W1" else {}, now)
            self.assertIn("war.preparation", fired, key)

    def test_inactive_members_announces_once_per_day(self):
        now = datetime.now(timezone.utc)
        self._clan([0, 0, 500])
        fired1, state = self._tick({}, now)
        self.assertIn("clan.inactive", fired1)
        for _ in range(4):
            fired, state = self._tick(state, now)
            self.assertNotIn("clan.inactive", fired)

    def test_donation_weekly_sends_once_in_the_hour(self):
        monday = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)  # Monday 05:00
        self.assertEqual(monday.weekday(), 0)
        self._clan([100, 50])
        sends = 0
        state = {}
        for i in range(6):
            fired, state = self._tick(state, monday + timedelta(minutes=5 * i))
            sends += fired.count("clan.donation_weekly")
        self.assertEqual(sends, 1)

    def test_donation_reset_detected_after_an_earlier_tick(self):
        """The old lastSeen guard blocked the reset on any day already ticked."""
        before = datetime(2026, 11, 22, 0, 5, tzinfo=timezone.utc)
        self._clan([5000, 4000])
        _, state = self._tick({}, before)
        self.assertEqual(state["clan"]["donations"]["total"], 9000)

        after = datetime(2026, 11, 22, 8, 5, tzinfo=timezone.utc)
        self._clan([10, 5])
        fired, _ = self._tick(state, after)
        self.assertIn("clan.donation_reset", fired)

    def test_raid_summary_fires_when_the_raid_ends(self):
        now = datetime.now(timezone.utc)
        for state_value, expect in (("ongoing", "raid.start"), ("ended", "raid.summary")):
            self._write("raid_stats", "raid_1.json", ["raid_1.json"], {
                "state": state_value, "startTime": "R1",
                "endTime": "20261116T070000.000Z", "capitalTotalLoot": 100,
                "totalAttacks": 3, "members": [
                    {"tag": "#M0", "name": "M0", "attacks": 1,
                     "attackLimit": 5, "capitalResourcesLooted": 50},
                ],
            })
            fired, state = self._tick(state if state_value == "ended" else {}, now)
            self.assertIn(expect, fired, state_value)

    def test_unconfigured_channel_does_not_claim_the_marker(self):
        """A missing channel must retry next tick, not silently eat the event."""
        self.config.set_channel(1, "all", 0)
        channel = FakeChannel()
        dispatcher = Dispatcher(FakeBot(channel), self.reader, self.config,
                                StateStore(self.cfg_dir))
        now = datetime.now(timezone.utc)
        self._war(hours_left=1, attacks_used=1)
        self.assertEqual(__import__("asyncio").run(dispatcher.tick(now)), 0)
        self.assertEqual(channel.sent, [])
        self.assertNotIn("war.ending_soon", (dispatcher.states.get(1).get("war") or {}))

    def test_tick_marks_delivered_events_only(self):
        channel = FakeChannel()
        dispatcher = Dispatcher(FakeBot(channel), self.reader, self.config,
                                StateStore(self.cfg_dir))
        now = datetime.now(timezone.utc)
        self._war(hours_left=1, attacks_used=1)
        sent = __import__("asyncio").run(dispatcher.tick(now))
        self.assertGreaterEqual(sent, 1)
        self.assertGreaterEqual(len(channel.sent), 1)
        state = dispatcher.states.get(1)
        self.assertEqual(state["war"]["ending_soon_key"], "W1")
        self.assertEqual(state["war"]["reminder_key"], "W1")

    def test_prime_records_state_without_sending(self):
        channel = FakeChannel()
        dispatcher = Dispatcher(FakeBot(channel), self.reader, self.config,
                                StateStore(self.cfg_dir))
        self._war(hours_left=1, attacks_used=1)
        dispatcher.prime()
        self.assertEqual(channel.sent, [])
        state = dispatcher.states.get(1)
        self.assertEqual(state["war"]["ending_soon_key"], "W1")


class TestScraperAbsent(unittest.TestCase):
    """The scraper package is optional; five events must still say something."""

    def setUp(self):
        import bot.events as events
        self.events = events
        self._saved = events.scraper_embeds
        events.scraper_embeds = None

    def tearDown(self):
        self.events.scraper_embeds = self._saved

    def _ctx(self, **kw):
        ctx = {"war": {}, "raid": {}, "clan": {}, "meta": {},
               "reader": None, "now": datetime.now(timezone.utc), "prev": {}}
        ctx.update(kw)
        return ctx

    def test_war_preparation_falls_back(self):
        war = {"state": "preparation", "startTime": "W1", "teamSize": 15,
               "clan": {"name": "99N"}, "opponent": {"name": "Foe"}}
        self.assertEqual(len(self.events.NOTIFY_EVENTS["war.preparation"](self._ctx(war=war), {})), 1)

    def test_war_result_falls_back(self):
        war = {"state": "warEnded", "startTime": "W1", "teamSize": 15, "attacksPerMember": 2,
               "clan": {"name": "99N", "stars": 44, "destructionPercentage": 62.5, "attacks": 17},
               "opponent": {"name": "Foe", "stars": 40, "destructionPercentage": 71.2, "attacks": 19}}
        self.assertEqual(len(self.events.NOTIFY_EVENTS["war.result"](self._ctx(war=war), {})), 1)

    def test_raid_events_fall_back(self):
        raid = {"state": "ongoing", "startTime": "R1", "endTime": "20261116T070000.000Z",
                "capitalTotalLoot": 100, "totalAttacks": 3, "members": []}
        self.assertEqual(len(self.events.NOTIFY_EVENTS["raid.start"](self._ctx(raid=raid), {})), 1)
        raid["state"] = "ended"
        self.assertEqual(
            len(self.events.NOTIFY_EVENTS["raid.summary"](self._ctx(raid=raid), {"raid": {"state": "ongoing"}})),
            1,
        )

    def test_roster_change_falls_back(self):
        clan = {"memberList": [{"tag": "#A", "name": "A"}, {"tag": "#NEW", "name": "New"}]}
        prev = {"clan": {"memberTags": ["#A"]}}
        self.assertEqual(
            len(self.events.NOTIFY_EVENTS["clan.roster"](self._ctx(clan=clan), prev)), 1
        )

    def test_donation_reset_falls_back(self):
        clan = {"memberList": [{"tag": "#A", "name": "A", "donations": 5}]}
        prev = {"clan": {"donations": {"total": 9000, "received": 200}}}
        self.assertEqual(
            len(self.events.NOTIFY_EVENTS["clan.donation_reset"](self._ctx(clan=clan), prev)), 1
        )


if __name__ == "__main__":
    unittest.main()
