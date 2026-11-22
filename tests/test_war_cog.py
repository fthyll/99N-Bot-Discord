import unittest

from bot.cogs.war import attacks_left, attack_summary, build_lineup, build_war_embed
from bot.cogs.raid import build_raid_embed, raid_absentees, raid_member_rows


WAR = {
    "state": "inWar",
    "teamSize": 15,
    "attacksPerMember": 2,
    "battleModifier": "none",
    "startTime": "20261115T024959.000Z",
    "endTime": "20261116T024959.000Z",
    "clan": {
        "tag": "#2J0YP2LQL",
        "name": "99N",
        "clanLevel": 4,
        "attacks": 17,
        "stars": 44,
        "destructionPercentage": 62.5,
        "members": [
            {"tag": "#A", "name": "Alpha", "townhallLevel": 18, "mapPosition": 12,
             "opponentAttacks": 1, "bestOpponentAttack": None},
            {"tag": "#B", "name": "Beta", "townhallLevel": 8, "mapPosition": 5,
             "opponentAttacks": 0, "bestOpponentAttack": None},
        ],
    },
    "opponent": {
        "tag": "#G0V8LUY98",
        "name": "Enemy Clan",
        "clanLevel": 9,
        "attacks": 30,
        "stars": 40,
        "destructionPercentage": 71.2,
        "members": [],
    },
}


class TestWarCog(unittest.TestCase):
    def test_attacks_left(self):
        # 15 * 2 = 30 possible, 17 used -> 13 left.
        self.assertEqual(attacks_left(WAR), 13)

    def test_attacks_left_zero_when_full(self):
        war = dict(WAR)
        war["clan"] = dict(WAR["clan"], attacks=30)
        self.assertEqual(attacks_left(war), 0)

    def test_attack_summary_counts_members_without_attacks(self):
        rows = attack_summary(WAR)
        self.assertEqual(len(rows), 2)
        without = [r for r in rows if r["attacks"] == 0]
        self.assertEqual([r["name"] for r in without], ["Beta"])

    def test_build_lineup_pairs_positions(self):
        rows = build_lineup(WAR)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["position"] for r in rows}, {12, 5})
        by_pos = {r["position"]: r for r in rows}
        self.assertEqual(by_pos[12]["th"], 18)
        self.assertEqual(by_pos[12]["opponent_th"], None)

    def test_build_war_embed(self):
        embed = build_war_embed(WAR)
        self.assertIn("99N", embed.title)
        self.assertTrue(len(embed.fields) >= 3)

    def test_build_war_embed_no_snapshot(self):
        embed = build_war_embed({})
        self.assertIn("No war", embed.description)


if __name__ == "__main__":
    unittest.main()
