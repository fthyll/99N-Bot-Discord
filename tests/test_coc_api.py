"""CocClient against canned API payloads, no network.

The three things that quietly produce wrong numbers rather than errors:
  * 404 notInWar is a normal answer, not an exception — war commands must say
    "no war", and a raise here would surface as a command crash between wars.
  * /capitalraidseasons is newest-first, so taking items[0] is only correct if
    the API order is trusted; the test pins that assumption.
  * a CWL war is visible from both sides, so counting each war from both sides
    doubles every row in the standings table.
"""

import os
import tempfile
import unittest

from bot.coc_api import CocClient, CocApiError, build_reader
from bot.snapshots import SnapshotReader

CLAN = {
    "tag": "#2J0YP2LQL",
    "name": "99N",
    "clanPoints": 42123,
    "location": {"id": 32000006, "name": "International", "isCountry": False},
    "warLeague": {"id": 48000006, "name": "Silver League I"},
    "memberList": [
        {"tag": "#A", "name": "Alpha", "townHallLevel": 18, "donations": 10},
        {"tag": "#B", "name": "Beta", "townHallLevel": 17, "donations": 0},
    ],
}


class FakeClient(CocClient):
    """CocClient with _get replaced by a dict lookup. Records call counts.

    Matching is by substring, longest key first, because the real paths nest:
    ``/clans/2J0YP2LQL/currentwar`` must hit the currentwar stub, not the clan
    stub that also prefixes it.
    """

    def __init__(self, responses, **kw):
        tmp = tempfile.mkdtemp()
        super().__init__(tmp, token="t", clan_tag="#2J0YP2LQL", **kw)
        self.responses = responses
        self.calls = []

    def _get(self, path):
        self.calls.append(path)
        clean = path.split("?")[0]
        # Longest key first: "/clans/TAG/currentwar" must win over the
        # "/clans/TAG" key that also prefixes it.
        for key in sorted(self.responses, key=len, reverse=True):
            if clean.startswith(key):
                return self.responses[key]
        return 404, {"reason": "notFound"}


class TestTransport(unittest.TestCase):
    def test_empty_token_is_rejected_with_an_actionable_message(self):
        with self.assertRaises(CocApiError) as ctx:
            CocClient(tempfile.mkdtemp(), token="", clan_tag="#X")
        self.assertIn("COC_API_TOKEN", str(ctx.exception))

    def test_missing_clan_tag_is_rejected(self):
        with self.assertRaises(CocApiError):
            CocClient(tempfile.mkdtemp(), token="t", clan_tag="  ")

    def test_404_not_in_war_returns_empty_not_an_exception(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN),
                             "/clans/2J0YP2LQL/currentwar": (404, {"reason": "notInWar"})})
        self.assertEqual(client.war(), {})

    def test_an_unexpected_404_degrades_to_the_snapshot(self):
        """Anything that is not notInWar means "we do not know" — use the file."""
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN),
                             "/clans/2J0YP2LQL/currentwar": (404, {"reason": "notFound"})})
        self.assertEqual(client.war(), {})
        self.assertEqual(client.last_errors.get("war"), "HTTP 404")

    def test_private_warlog_degrades_to_the_snapshot(self):
        """A permanently private log must not break /warstats."""
        client = FakeClient({"/clans/2J0YP2LQL/warlog": (403, {"reason": "accessDenied"})})
        self.assertEqual(client.warlog(), [])
        self.assertEqual(client.last_errors.get("warlog"), "HTTP 403")

    def test_an_unexpected_status_degrades_and_is_recorded(self):
        """A rotated token or a Supercell outage must not crash a command."""
        client = FakeClient({"/clans/2J0YP2LQL": (500, {"reason": "unknown"})})
        self.assertEqual(client.clan(), {})
        self.assertEqual(client.last_errors.get("clan"), "HTTP 500")

    def test_a_missing_clan_tag_is_still_a_hard_error(self):
        """A wrong CLAN_TAG is a config bug, not a transient failure."""
        client = FakeClient({"/clans/2J0YP2LQL": (404, {"reason": "notFound"})})
        with self.assertRaises(CocApiError) as ctx:
            client.clan()
        self.assertIn("CLAN_TAG", str(ctx.exception))


class TestPayloadMapping(unittest.TestCase):
    def test_members_come_from_the_same_request_as_clan(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN)})
        self.assertEqual(len(client.members()), 2)
        # clan() and members() must not cost two requests.
        self.assertEqual(len([c for c in client.calls if c.startswith("/clans/")]), 1)

    def test_raid_takes_the_newest_weekend(self):
        newest = {"startTime": "20261121T070000.000Z", "state": "ongoing"}
        older = {"startTime": "20261114T070000.000Z", "state": "ended"}
        client = FakeClient({"/clans/2J0YP2LQL/capitalraidseasons": (200, {"items": [newest, older]})})
        self.assertEqual(client.raid()["startTime"], newest["startTime"])

    def test_no_raid_weekends_at_all_is_an_empty_state(self):
        client = FakeClient({"/clans/2J0YP2LQL/capitalraidseasons": (200, {"items": []})})
        self.assertEqual(client.raid(), {})

    def test_players_skips_a_member_the_api_refuses(self):
        roster = {"/clans/2J0YP2LQL": (200, CLAN),
                  "/players/A": (200, {"tag": "#A", "name": "Alpha", "warStars": 900}),
                  "/players/B": (403, {"reason": "accessDenied"})}
        client = FakeClient(roster)
        players = client.players()
        self.assertEqual(list(players), ["#A"])
        self.assertEqual(players["#A"]["warStars"], 900)

    def test_players_respects_the_limit(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN),
                             "/players/": (200, {"tag": "#X"})}, player_limit=1)
        self.assertEqual(len(client.players()), 1)

    def test_meta_defaults_to_out_of_season_when_the_group_404s(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN),
                             "/goldpass/seasons/current": (200, {"startTime": "20261101T080000.000Z"}),
                             "/clans/2J0YP2LQL/currentwar/leaguegroup": (404, {"reason": "notInSeason"})})
        meta = client.meta()
        self.assertEqual(meta["cwl"], {"state": "notInSeason"})
        self.assertEqual(meta["goldpass"]["startTime"], "20261101T080000.000Z")
        self.assertEqual(meta["countryRank"]["locationName"], "International")


class TestLeagueStandings(unittest.TestCase):
    """A CWL war is reported identically to both clans; count it once."""

    def _group(self):
        return {
            "state": "inWar",
            "season": "2026-11",
            "rounds": [{"warTags": ["#W1"]}, {"warTags": ["#0"]}],
        }

    def _war(self):
        # #AAA beat #BBB 10 stars to 5.
        return {
            "state": "warEnded",
            "winner": "clan",
            "clan": {"tag": "#AAA", "name": "Us", "stars": 10},
            "opponent": {"tag": "#BBB", "name": "Them", "stars": 5},
        }

    def test_each_war_is_counted_once_not_from_both_sides(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN),
                             "/clans/2J0YP2LQL/currentwar/leaguegroup": (200, self._group()),
                             "/clanwarleagues/wars/": (200, self._war())})
        rows = client.meta()["cwl"]["standings"]
        self.assertEqual(len(rows), 2, "two clans, two rows — not four")
        by_tag = {r["tag"]: r for r in rows}
        self.assertEqual((by_tag["#AAA"]["wins"], by_tag["#AAA"]["losses"]), (1, 0))
        self.assertEqual((by_tag["#BBB"]["wins"], by_tag["#BBB"]["losses"]), (0, 1))

    def test_standings_are_ordered_by_points_then_stars(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN),
                             "/clans/2J0YP2LQL/currentwar/leaguegroup": (200, self._group()),
                             "/clanwarleagues/wars/": (200, self._war())})
        rows = client.meta()["cwl"]["standings"]
        self.assertEqual([r["position"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["tag"], "#AAA")

    def test_placeholder_war_tags_are_ignored(self):
        group = self._group()
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN),
                             "/clans/2J0YP2LQL/currentwar/leaguegroup": (200, group),
                             "/clanwarleagues/wars/": (200, self._war())})
        client.meta()
        fetched = [c for c in client.calls if c.startswith("/clanwarleagues/")]
        self.assertEqual(len(fetched), 1, "#0 is a placeholder, never fetched")

    def test_unplayed_wars_do_not_create_rows(self):
        blank = {"state": "preparation", "clan": {"tag": "#AAA"}, "opponent": {"tag": "#BBB"}}
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN),
                             "/clans/2J0YP2LQL/currentwar/leaguegroup": (200, self._group()),
                             "/clanwarleagues/wars/": (200, blank)})
        self.assertEqual(client.meta()["cwl"]["standings"], [])


class TestCaching(unittest.TestCase):
    def test_repeated_reads_do_not_hammer_the_api(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN)}, cache_seconds=600)
        client.clan(); client.clan(); client.members(); client.members()
        self.assertEqual(len([c for c in client.calls if c.startswith("/clans/")]), 1)

    def test_cache_can_be_disabled(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN)}, cache_seconds=0)
        client.clan(); client.clan()
        self.assertEqual(len([c for c in client.calls if c.startswith("/clans/")]), 2)

    def test_invalidate_forces_a_refetch(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN)}, cache_seconds=600)
        client.clan(); client.invalidate(); client.clan()
        self.assertEqual(len([c for c in client.calls if c.startswith("/clans/")]), 2)


class TestFreshnessAndTrends(unittest.TestCase):
    def test_live_reader_reports_itself_as_fresh(self):
        client = FakeClient({"/clans/2J0YP2LQL": (200, CLAN)})
        age = client.age_hours(client.freshest_stamp())
        self.assertIsNotNone(age)
        self.assertLess(age, 0.05)

    def test_trends_fall_back_to_the_committed_archive(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "player_trends.json"), "w") as fh:
            fh.write('{"players": {"#A": [{"date": "2026-11-01", "trophies": 1}]}}')
        client = CocClient(tmp, token="t", clan_tag="#X")
        self.assertEqual(client.trends()["players"]["#A"][0]["trophies"], 1)


class TestFactory(unittest.TestCase):
    def test_no_token_selects_the_offline_reader(self):
        self.assertIsInstance(build_reader(tempfile.mkdtemp()), SnapshotReader)
        self.assertIsInstance(
            build_reader(tempfile.mkdtemp(), token="", clan_tag="#2J0YP2LQL"),
            SnapshotReader,
        )

    def test_token_selects_the_live_client(self):
        reader = build_reader(tempfile.mkdtemp(), token="t", clan_tag="#2J0YP2LQL")
        self.assertIsInstance(reader, CocClient)

    def test_switching_modes_needs_no_code_change(self):
        """Both readers answer every method the cogs call."""
        tmp = tempfile.mkdtemp()
        for reader in (SnapshotReader(tmp),
                       CocClient(tmp, token="t", clan_tag="#2J0YP2LQL")):
            for method in ("clan", "members", "war", "raid", "players",
                           "warlog", "meta", "trends", "age_hours",
                           "freshest_stamp", "sync_time", "index", "latest"):
                self.assertTrue(callable(getattr(reader, method)),
                                f"{type(reader).__name__} lacks {method}")


if __name__ == "__main__":
    unittest.main()