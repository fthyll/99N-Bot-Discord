import unittest

from bot.cogs.player import build_compare_embed, build_top_embed, build_trend_embed


class TestPlayerCog(unittest.TestCase):
    def test_top_embed(self):
        rows = [{"name": "A", "tag": "#A", "townHallLevel": 18, "warStars": 900}]
        embed = build_top_embed(rows, "warStars")
        self.assertIn("A", embed.description)

    def test_top_embed_empty(self):
        self.assertIn("No data", build_top_embed([], "warStars").description)

    def test_trend_embed(self):
        member = {"name": "A", "tag": "#A"}
        points = [
            {"date": "2026-11-13", "trophies": 300, "donations": 10, "warStars": 900},
            {"date": "2026-11-15", "trophies": 400, "donations": 20, "warStars": 905},
        ]
        embed = build_trend_embed(member, points)
        self.assertIn("2026-11-15", embed.description)
        self.assertEqual(embed.fields[0].value, "+100")

    def test_trend_embed_empty(self):
        self.assertIn("No trend", build_trend_embed({"name": "A"}, []).description)

    def test_compare_embed(self):
        one = {"name": "A", "tag": "#A", "trophies": 500, "donations": 100}
        two = {"name": "B", "tag": "#B", "trophies": 300, "donations": 50}
        embed = build_compare_embed(one, two)
        self.assertIn("500 vs 300", embed.description)


if __name__ == "__main__":
    unittest.main()
