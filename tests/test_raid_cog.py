import unittest

from bot.cogs.raid import build_raid_embed, raid_absentees, raid_member_rows

RAID = {
    "state": "ended",
    "startTime": "20261113T070000.000Z",
    "endTime": "20261116T070000.000Z",
    "capitalTotalLoot": 1234567,
    "raidsCompleted": 12,
    "totalAttacks": 42,
    "enemyDistrictsDestroyed": 4,
    "offensiveReward": 1500,
    "defensiveReward": 900,
    "members": [
        {"tag": "#A", "name": "Alpha", "attacks": 5, "attackLimit": 5,
         "bonusAttackLimit": 0, "capitalResourcesLooted": 500000},
        {"tag": "#B", "name": "Beta", "attacks": 0, "attackLimit": 5,
         "bonusAttackLimit": 0, "capitalResourcesLooted": 0},
    ],
}


class TestRaidCog(unittest.TestCase):
    def test_member_rows_sorted_by_loot(self):
        rows = raid_member_rows(RAID)
        self.assertEqual([r["name"] for r in rows], ["Alpha", "Beta"])
        self.assertEqual(rows[0]["limit"], 5)

    def test_absentees(self):
        absent = raid_absentees(RAID)
        self.assertEqual([r["name"] for r in absent], ["Beta"])

    def test_raid_embed(self):
        embed = build_raid_embed(RAID)
        self.assertIn("Capital raid", embed.title)
        self.assertIn("1,234,567", embed.description)

    def test_raid_embed_missing(self):
        embed = build_raid_embed({})
        self.assertIn("No raid", embed.description)


if __name__ == "__main__":
    unittest.main()
