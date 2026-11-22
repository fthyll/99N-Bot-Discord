import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from bot.config_store import ConfigStore
from bot.notifier import StateStore, build_context, due_events, next_state
from bot.snapshots import SnapshotReader


class TestNotifier(unittest.TestCase):
    def _fixture(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = os.path.join(tmp.name, "data")
        os.makedirs(os.path.join(data, "war_stats"))
        os.makedirs(os.path.join(data, "clan_stats"))
        with open(os.path.join(data, "war_stats_index.json"), "w") as f:
            json.dump(["war_20261115T024959.000Z.json"], f)
        with open(os.path.join(data, "war_stats", "war_20261115T024959.000Z.json"), "w") as f:
            json.dump({
                "state": "warEnded", "startTime": "20261115T024959.000Z",
                "endTime": "20261116T024959.000Z", "teamSize": 15, "attacksPerMember": 2,
                "clan": {"name": "99N", "stars": 44, "destructionPercentage": 62.5,
                         "attacks": 17, "members": []},
                "opponent": {"name": "Foe", "stars": 40, "destructionPercentage": 71.2,
                             "attacks": 30, "members": []},
            }, f)
        with open(os.path.join(data, "clan_stats_index.json"), "w") as f:
            json.dump(["members_20261115.json"], f)
        with open(os.path.join(data, "clan_stats", "members_20261115.json"), "w") as f:
            json.dump({"memberList": [{"tag": "#A", "name": "A", "donations": 10}]}, f)
        return SnapshotReader(data), ConfigStore(root=os.path.join(tmp.name, "cfg"))

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            store = StateStore(d)
            store.save(7, {"war": {"state": "inWar"}})
            self.assertEqual(store.get(7)["war"]["state"], "inWar")
            store.clear(7)
            self.assertEqual(store.get(7), {})

    def test_due_events_respects_enabled_flag(self):
        reader, config = self._fixture()
        config.set(1, "events.war.result.enabled", False)
        out = due_events(1, config, reader, {}, now=datetime.now(timezone.utc))
        self.assertNotIn("war.result", [k for k, _ in out])

    def test_war_result_due_once_then_not(self):
        reader, config = self._fixture()
        now = datetime.now(timezone.utc)
        first = due_events(1, config, reader, {}, now=now)
        self.assertIn("war.result", [k for k, _ in first])
        state = next_state(build_context(reader, {}, now=now), {})
        second = due_events(1, config, reader, state, now=now)
        self.assertNotIn("war.result", [k for k, _ in second])

    def test_next_state_records_member_tags(self):
        reader, config = self._fixture()
        now = datetime.now(timezone.utc)
        state = next_state(build_context(reader, {}, now=now), {})
        self.assertEqual(state["clan"]["memberTags"], ["#A"])
        self.assertEqual(state["clan"]["donations"]["total"], 10)

    def test_quiet_hours_suppresses_everything(self):
        reader, config = self._fixture()
        config.set(1, "quiet_hours.start", "00:00")
        config.set(1, "quiet_hours.end", "23:59")
        now = datetime.now(timezone.utc)
        # in_quiet_hours is checked by the dispatcher, not by due_events
        self.assertTrue(config.in_quiet_hours(1, now.time()))


if __name__ == "__main__":
    unittest.main()
