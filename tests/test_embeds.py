import unittest

from bot.embeds import dict_to_embed, player_card, player_lookup


class TestEmbeds(unittest.TestCase):
    def test_dict_to_embed(self):
        raw = {
            "title": "War",
            "description": "desc",
            "color": 0xF5B942,
            "fields": [{"name": "a", "value": "b", "inline": True}],
            "footer": {"text": "foot"},
        }
        embed = dict_to_embed(raw)
        self.assertEqual(embed.title, "War")
        self.assertEqual(embed.description, "desc")
        self.assertEqual(len(embed.fields), 1)
        self.assertEqual(embed.fields[0].name, "a")
        self.assertEqual(embed.footer.text, "foot")

    def test_dict_to_embed_empty(self):
        embed = dict_to_embed({})
        self.assertIsNotNone(embed)

    def test_player_card_thumbnail_is_attachment(self):
        embed, filename = player_card({"name": "Vey", "townHallLevel": 18, "tag": "#ABC"})
        self.assertEqual(filename, "Town_Hall18.webp")
        self.assertEqual(embed.thumbnail.url, "attachment://Town_Hall18.webp")
        self.assertIn("Vey", embed.title)

    def test_player_card_defaults_to_th1(self):
        embed, filename = player_card({"name": "X"})
        self.assertEqual(filename, "Town_Hall1.webp")

    def test_player_lookup_by_name_and_tag(self):
        members = [
            {"tag": "#ABC123", "name": "NOBIT", "townHallLevel": 18},
            {"tag": "#XYZ789", "name": "AQUAx99N", "townHallLevel": 8},
        ]
        self.assertEqual(player_lookup(members, "nobi")["tag"], "#ABC123")
        self.assertEqual(player_lookup(members, "AQUA")["tag"], "#XYZ789")
        self.assertEqual(player_lookup(members, "abc123")["tag"], "#ABC123")
        self.assertEqual(player_lookup(members, "#XYZ789")["tag"], "#XYZ789")
        self.assertIsNone(player_lookup(members, "nobody"))


if __name__ == "__main__":
    unittest.main()
