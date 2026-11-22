import json
import os
import tempfile
import unittest

from bot.snapshots import SnapshotReader


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


class TestSnapshotIndexOrder(unittest.TestCase):
    """The archive uses two opposite index orders; latest() must honour both.

    player_stats is newest-first exactly like clan_stats. Reading it as
    oldest-first silently served a snapshot from two months earlier.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, "data")

    def _seed(self, folder, names, payloads):
        for name, payload in zip(names, payloads):
            _write(os.path.join(self.data, folder, name), payload)
        _write(os.path.join(self.data, f"{folder}_index.json"), names)

    def test_player_stats_newest_first(self):
        self._seed(
            "player_stats",
            ["players_new.json", "players_old.json"],
            [{"fetchedAt": "2026-11-15T00:00:00Z", "players": {"#NEW": {"name": "new"}}},
             {"fetchedAt": "2026-09-16T00:00:00Z", "players": {"#OLD": {"name": "old"}}}],
        )
        reader = SnapshotReader(self.data)
        self.assertEqual(reader.players(), {"#NEW": {"name": "new"}})
        self.assertEqual(reader.latest("player_stats")["fetchedAt"], "2026-11-15T00:00:00Z")

    def test_clan_stats_newest_first(self):
        self._seed(
            "clan_stats",
            ["members_new.json", "members_old.json"],
            [{"memberList": [{"tag": "#NEW"}]}, {"memberList": [{"tag": "#OLD"}]}],
        )
        self.assertEqual(SnapshotReader(self.data).members(), [{"tag": "#NEW"}])

    def test_war_stats_oldest_first(self):
        self._seed(
            "war_stats",
            ["war_old.json", "war_new.json"],
            [{"state": "warEnded", "startTime": "OLD"}, {"state": "inWar", "startTime": "NEW"}],
        )
        self.assertEqual(SnapshotReader(self.data).war()["startTime"], "NEW")

    def test_raid_stats_oldest_first(self):
        self._seed(
            "raid_stats",
            ["raid_old.json", "raid_new.json"],
            [{"state": "ended", "startTime": "OLD"}, {"state": "ongoing", "startTime": "NEW"}],
        )
        self.assertEqual(SnapshotReader(self.data).raid()["startTime"], "NEW")

    def test_player_trends_and_meta(self):
        _write(os.path.join(self.data, "player_trends.json"),
               {"players": {"#A": [{"date": "2026-11-15", "trophies": 400}]}})
        _write(os.path.join(self.data, "meta.json"), {"fetchedAt": "2026-11-15T16:10:29Z"})
        reader = SnapshotReader(self.data)
        self.assertEqual(reader.trends()["players"]["#A"][0]["trophies"], 400)
        self.assertEqual(reader.meta()["fetchedAt"], "2026-11-15T16:10:29Z")

    def test_missing_files_degrade_to_empty(self):
        reader = SnapshotReader(os.path.join(self.tmp.name, "nope"))
        self.assertEqual(reader.players(), {})
        self.assertEqual(reader.war(), {})
        self.assertEqual(reader.members(), [])
        self.assertEqual(reader.meta(), {})
        self.assertIsNone(reader.freshest_stamp())


if __name__ == "__main__":
    unittest.main()
