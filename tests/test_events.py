import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from bot.config_store import ConfigStore
from bot.events import NOTIFY_EVENTS, event_keys
from bot.snapshots import SnapshotReader


class TestEvents(unittest.TestCase):
    def test_all_keys_have_callable_trigger(self):
        for key in event_keys():
            self.assertTrue(callable(NOTIFY_EVENTS[key]), key)

    def test_fourteen_events(self):
        self.assertEqual(len(event_keys()), 14)

    def test_config_has_every_event(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = ConfigStore(root=d).get(1)
        for key in event_keys():
            self.assertIn(key, cfg["events"], key)

    def test_triggers_are_quiet_with_no_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            reader = SnapshotReader(d)
            ctx = {
                "war": {}, "raid": {}, "clan": {}, "meta": {},
                "reader": reader, "now": datetime.now(timezone.utc), "prev": {},
            }
            for key, trigger in NOTIFY_EVENTS.items():
                self.assertEqual(trigger(ctx, {}), [], key)

    def test_war_result_fires_once(self):
        war = {"state": "warEnded", "startTime": "20261115T024959.000Z",
               "teamSize": 15, "attacksPerMember": 2,
               "clan": {"name": "99N", "stars": 44, "destructionPercentage": 62.5,
                        "attacks": 17, "members": []},
               "opponent": {"name": "Foe", "stars": 40, "destructionPercentage": 71.2,
                            "attacks": 30, "members": []}}
        ctx = {"war": war, "raid": {}, "clan": {}, "meta": {},
               "reader": None, "now": datetime.now(timezone.utc), "prev": {}}
        first = NOTIFY_EVENTS["war.result"](ctx, {})
        self.assertEqual(len(first), 1)
        again = NOTIFY_EVENTS["war.result"](ctx, {"war": {"state": "warEnded", "key": war["startTime"]}})
        self.assertEqual(again, [])

    def test_war_ending_soon_skips_when_out_of_window(self):
        end = datetime.now(timezone.utc) + timedelta(hours=6)
        stamp = end.strftime("%Y%m%dT%H%M%S.000Z")
        war = {"state": "inWar", "endTime": stamp, "teamSize": 15,
               "attacksPerMember": 2, "clan": {"attacks": 0, "members": []}}
        ctx = {"war": war, "raid": {}, "clan": {}, "meta": {},
               "reader": None, "now": datetime.now(timezone.utc), "prev": {}}
        self.assertEqual(NOTIFY_EVENTS["war.ending_soon"](ctx, {}), [])


if __name__ == "__main__":
    unittest.main()
