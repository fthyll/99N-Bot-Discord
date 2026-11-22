import unittest

from bot.cogs.clan import (
    build_clan_embed,
    build_roster_embed,
    find_member,
    top_rows,
    inactive_members,
)

CLAN = {
    "tag": "#2J0YP2LQL",
    "name": "99N",
    "clanLevel": 4,
    "clanPoints": 23950,
    "warWins": 5,
    "warLosses": 6,
    "warTies": 0,
    "warWinStreak": 0,
    "requiredTrophies": 0,
    "warFrequency": "Always",
    "clanCapital": {"capitalHallLevel": 3, "districts": []},
    "warLeague": {"name": "Unranked"},
    "capitalLeague": {"name": "Bronze League III"},
    "memberList": [
        {"tag": "#A", "name": "Alpha", "role": "leader", "townHallLevel": 18,
         "trophies": 500, "donations": 1000, "donationsReceived": 400,
         "builderBaseTrophies": 2800, "clanRank": 1},
        {"tag": "#B", "name": "Beta", "role": "member", "townHallLevel": 8,
         "trophies": 300, "donations": 100, "donationsReceived": 50,
         "builderBaseTrophies": 1200, "clanRank": 2},
    ],
}


class TestClanCog(unittest.TestCase):
    def test_find_member_by_name_and_tag(self):
        members = CLAN["memberList"]
        self.assertEqual(find_member(members, "alpha")["tag"], "#A")
        self.assertEqual(find_member(members, "#B")["tag"], "#B")
        self.assertEqual(find_member(members, "b")["tag"], "#B")
        self.assertIsNone(find_member(members, "zzz"))

    def test_clan_embed(self):
        embed = build_clan_embed(CLAN)
        self.assertIn("99N", embed.title)
        self.assertTrue(len(embed.fields) >= 4)

    def test_clan_embed_missing(self):
        embed = build_clan_embed({})
        self.assertIn("No clan", embed.description)

    def test_roster_embed_filters_role(self):
        embed = build_roster_embed(CLAN["memberList"], role="leader")
        self.assertIn("Alpha", embed.description)
        self.assertNotIn("Beta", embed.description)

    def test_roster_embed_sorts_by_donations(self):
        embed = build_roster_embed(CLAN["memberList"], sort_key="donations")
        self.assertLess(embed.description.index("Alpha"), embed.description.index("Beta"))

    def test_top_rows(self):
        rows = top_rows(CLAN["memberList"], "donations", limit=1)
        self.assertEqual(rows[0]["name"], "Alpha")

    def test_inactive_members(self):
        rows = inactive_members([{"name": "A", "donations": 0}], days=7)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
