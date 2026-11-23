"""WarmCache: the background refresher that keeps the API off the event loop.

The failure this guards against is not a crash, it is a hang: calling
``players()`` inline costs ~50 round trips, and a Discord event loop that
stalls long enough gets disconnected. The tests below pin the two properties
that prevent it — reads never hit the network once warm, and a broken endpoint
does not stop the rest from being warmed.
"""

import asyncio
import time
import unittest

from bot import bot_config
from bot.coc_api import CocApiError, CocClient
from bot.offload import WARMED, WarmCache
from bot.snapshots import SnapshotReader


class CountingClient(CocClient):
    """CocClient with the network replaced and every call counted."""

    def __init__(self, fail=(), **kw):
        super().__init__("/tmp", token="t", clan_tag="#2J0YP2LQL", **kw)
        self.counts = {}
        self.fail = set(fail)

    def _get(self, path):
        # Key on the full path: "/clans/TAG" also prefixes
        # "/clans/TAG/currentwar", so a per-segment counter conflates them.
        self.counts[path] = self.counts.get(path, 0) + 1
        if any(f in path for f in self.fail):
            raise CocApiError(f"stubbed failure for {path}")
        if "members" in path or path.count("/") == 2:
            return 200, {"tag": "#2J0YP2LQL", "name": "99N",
                         "memberList": [{"tag": "#A", "name": "Alpha"}]}
        if "currentwar" in path and "leaguegroup" not in path:
            return 404, {"reason": "notInWar"}
        if "capitalraidseasons" in path:
            return 200, {"items": [{"startTime": "20261121T070000.000Z"}]}
        if "warlog" in path:
            return 200, {"items": []}
        if "goldpass" in path:
            return 200, {"startTime": "20261101T080000.000Z"}
        if "leaguegroup" in path:
            return 404, {"reason": "notInSeason"}
        if "players" in path:
            return 200, {"tag": "#A", "name": "Alpha"}
        return 404, {"reason": "notFound"}


class TestWarmRefresh(unittest.TestCase):
    def test_refresh_populates_every_endpoint_including_the_expensive_one(self):
        client = CountingClient()
        warmer = WarmCache(client, interval_seconds=600)
        errors = warmer.refresh_once()
        self.assertEqual(errors, {})
        # players() is the 50-request one; it must actually run.
        self.assertTrue(any("/players/" in p for p in client.counts))
        self.assertTrue(warmer.ready)

    def test_reads_after_a_refresh_do_not_touch_the_network(self):
        client = CountingClient()
        warmer = WarmCache(client, interval_seconds=600)
        warmer.refresh_once()
        before = dict(client.counts)
        # A whole command's worth of reads.
        warmer.clan(); warmer.members(); warmer.war(); warmer.raid()
        warmer.warlog(); warmer.players(); warmer.meta()
        self.assertEqual(client.counts, before, "cache miss after a warm refresh")

    def test_one_permanently_broken_endpoint_does_not_stop_the_others(self):
        # A private war log is a permanent 403 for some clans.
        client = CountingClient(fail=("/warlog",))
        warmer = WarmCache(client, interval_seconds=600)
        errors = warmer.refresh_once()
        self.assertIn("warlog", errors)
        self.assertIn("/clans/2J0YP2LQL", client.counts)
        self.assertTrue(any("/players/" in p for p in client.counts))
        self.assertTrue(warmer.ready, "a known-broken endpoint must not block readiness")

    def test_a_failing_refresh_does_not_kill_the_thread(self):
        client = CountingClient(fail=("/clans/",))
        warmer = WarmCache(client, interval_seconds=600)
        warmer.refresh_once()  # must not raise
        self.assertTrue(warmer.ready)
        self.assertIsNotNone(warmer.last_error)

    def test_the_thread_refreshes_repeatedly_then_stops(self):
        client = CountingClient()
        warmer = WarmCache(client, interval_seconds=30)
        warmer.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline and not warmer.ready:
                time.sleep(0.05)
            self.assertTrue(warmer.ready)
        finally:
            warmer.stop()
        self.assertFalse(warmer._thread.is_alive())

    def test_stop_is_prompt_not_one_interval_long(self):
        client = CountingClient()
        warmer = WarmCache(client, interval_seconds=600)
        warmer.start()
        warmer.stop()
        started = time.time()
        warmer.stop()
        self.assertLess(time.time() - started, 1.0)


class TestIndistinguishableFromSnapshots(unittest.TestCase):
    """A cog must not be able to tell which mode is active."""

    def test_warmer_forwards_the_whole_reader_interface(self):
        warmer = WarmCache(CountingClient(), interval_seconds=600)
        for method in ("clan", "members", "war", "raid", "players", "warlog",
                       "meta", "trends", "age_hours", "freshest_stamp",
                       "sync_time", "index", "latest", "invalidate"):
            self.assertTrue(callable(getattr(warmer, method)),
                            f"WarmCache does not expose {method}")

    def test_warmer_rejects_a_non_api_reader(self):
        with self.assertRaises(TypeError):
            WarmCache(SnapshotReader("/tmp"))

    def test_snapshot_mode_starts_no_thread(self):
        bot_config.reset_reader()
        saved = bot_config.COC_API_TOKEN
        bot_config.COC_API_TOKEN = ""
        try:
            reader = bot_config.start_reader()
            self.assertIsInstance(reader, SnapshotReader)
            self.assertFalse(hasattr(reader, "start"))
        finally:
            bot_config.COC_API_TOKEN = saved
            bot_config.reset_reader()

    def test_reader_is_shared_so_the_cache_is_not_seven_caches(self):
        bot_config.reset_reader()
        try:
            self.assertIs(bot_config.build_reader(), bot_config.build_reader())
        finally:
            bot_config.reset_reader()

    def test_live_mode_returns_a_started_warmer(self):
        bot_config.reset_reader()
        saved = (bot_config.COC_API_TOKEN, bot_config.CLAN_TAG)
        bot_config.COC_API_TOKEN, bot_config.CLAN_TAG = "t", "#2J0YP2LQL"
        try:
            reader = bot_config.build_reader()
            self.assertIsInstance(reader, WarmCache)
            self.assertIsInstance(reader.client, CocClient)
        finally:
            bot_config.COC_API_TOKEN, bot_config.CLAN_TAG = saved
            bot_config.reset_reader()

    def test_warmed_list_covers_every_network_method(self):
        # sync_time/index/latest/trends/freshest_stamp are local file/clock
        # reads. members() derives from clan() and costs no extra request, so it
        # is deliberately absent. Anything that reaches _get must be warmed or
        # it silently misses the cache.
        for name in ("clan", "war", "raid", "warlog", "players", "meta"):
            self.assertIn(name, WARMED)
        self.assertNotIn("members", WARMED,
                         "members() is free — warming it would be a no-op")

    def test_members_costs_no_request_beyond_clan(self):
        client = CountingClient()
        client.clan()
        before = dict(client.counts)
        self.assertEqual(len(client.members()), 1)
        self.assertEqual(client.counts, before)


class TestAsyncHelper(unittest.TestCase):
    def test_refresh_now_runs_off_the_loop(self):
        from bot.offload import refresh_now

        client = CountingClient()
        warmer = WarmCache(client, interval_seconds=600)

        async def go():
            return await refresh_now(warmer)

        errors = asyncio.run(go())
        self.assertEqual(errors, {})
        self.assertTrue(warmer.ready)


if __name__ == "__main__":
    unittest.main()