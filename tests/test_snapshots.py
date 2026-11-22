import json
import os
import tempfile
import unittest

from bot.snapshots import SnapshotReader


class TestSnapshotReader(unittest.TestCase):
    def _reader(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return SnapshotReader(tmp.name)

    def test_latest_war_by_filename(self):
        r = self._reader()
        os.makedirs(os.path.join(r.data_dir, "war_stats"))
        for name in ("war_20260101T000000.000Z.json", "war_20261115T024959.000Z.json"):
            with open(os.path.join(r.data_dir, "war_stats", name), "w") as f:
                json.dump({"state": "warEnded", "startTime": name[4:12]}, f)
        war = r.latest("war_stats")
        self.assertEqual(war["startTime"], "20261115")

    def test_latest_clan_uses_index_newest_first(self):
        r = self._reader()
        os.makedirs(os.path.join(r.data_dir, "clan_stats"))
        # Index is newest-first for clan snapshots (README documents the
        # exception: war/raid indices are oldest-first).
        with open(os.path.join(r.data_dir, "clan_stats_index.json"), "w") as f:
            json.dump(["members_20261115.json", "members_20261114.json"], f)
        for name in ("members_20261115.json", "members_20261114.json"):
            with open(os.path.join(r.data_dir, "clan_stats", name), "w") as f:
                json.dump({"name": name}, f)
        clan = r.latest("clan_stats")
        self.assertEqual(clan["name"], "members_20261115.json")

    def test_latest_missing_returns_empty(self):
        r = self._reader()
        self.assertEqual(r.latest("war_stats"), {})

    def test_members_list(self):
        r = self._reader()
        os.makedirs(os.path.join(r.data_dir, "clan_stats"))
        with open(os.path.join(r.data_dir, "clan_stats", "members_20261115.json"), "w") as f:
            json.dump({"memberList": [{"tag": "#A", "name": "X"}]}, f)
        self.assertEqual(len(r.members()), 1)

    def test_age_hours_from_fetched_at(self):
        r = self._reader()
        self.assertIsNone(r.age_hours(None))
        import datetime
        now = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc)
        fetched = "2026-11-16T00:00:00Z"
        self.assertAlmostEqual(r.age_hours(fetched, now=now), 12.0, places=1)


if __name__ == "__main__":
    unittest.main()
