"""Tests for the enriched embeds, the formatting helpers and the log pipeline."""

import asyncio
import logging
import os
import tempfile
import unittest
from pathlib import Path

import discord

from bot import bot_config
from bot.cogs.admin import build_config_summary, build_notif_table
from bot.cogs.clan import build_clan_embed, top_rows
from bot.cogs.raid import build_raid_embed, raid_absentees, raid_member_rows
from bot.cogs.war import attack_summary, build_war_embed, build_warstats_embed
from bot.discord_log import DiscordLogHandler
from bot.formatting import bar, form, medal, pct, truncate


class BarTests(unittest.TestCase):
    def test_ends_are_full_and_empty(self):
        self.assertEqual(bar(0, 10, width=4), "░░░░")
        self.assertEqual(bar(10, 10, width=4), "████")

    def test_half_fills_half_the_width(self):
        self.assertEqual(bar(5, 10, width=10), "█████░░░░░")

    def test_non_zero_value_never_renders_empty(self):
        # 1/1000 rounds to zero blocks; an empty bar for a non-zero value is a
        # lie in a progress display.
        self.assertEqual(bar(1, 1000, width=8), "█░░░░░░░")

    def test_over_capacity_is_clamped(self):
        self.assertEqual(bar(20, 10, width=4), "████")

    def test_zero_total_and_garbage_yield_empty(self):
        self.assertEqual(bar(5, 0, width=3), "░░░")
        self.assertEqual(bar(None, None, width=3), "░░░")
        self.assertEqual(bar("x", "y", width=3), "░░░")


class PctTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(pct(1, 4), "25.0%")

    def test_zero_whole_is_dash(self):
        self.assertEqual(pct(3, 0), "—")
        self.assertEqual(pct(None, 5), "0.0%")


class FormTests(unittest.TestCase):
    def test_maps_results_to_marks(self):
        self.assertEqual(form(["win", "lose", "draw"]), "🟩🟥🟨")

    def test_keeps_only_the_tail(self):
        self.assertEqual(form(["win"] * 5 + ["lose"], limit=2), "🟩🟥")

    def test_unknown_and_empty(self):
        self.assertEqual(form(["banana"]), "⬜")
        self.assertEqual(form([]), "—")

    def test_case_insensitive(self):
        self.assertEqual(form(["WIN", "Lose"]), "🟩🟥")


class MedalTests(unittest.TestCase):
    def test_podium(self):
        self.assertEqual(medal(1), "🥇")
        self.assertEqual(medal(2), "🥈")
        self.assertEqual(medal(3), "🥉")

    def test_beyond_podium_is_a_number(self):
        self.assertEqual(medal(4), "`4.`")


class TruncateTests(unittest.TestCase):
    def test_respects_limit(self):
        out = truncate("x" * 100, limit=10)
        self.assertEqual(len(out), 10)
        self.assertTrue(out.endswith("..."))


CLAN = {
    "name": "99N",
    "tag": "#2ABC",
    "description": "war clan",
    "clanLevel": 12,
    "clanPoints": 34567,
    "warWins": 30,
    "warLosses": 10,
    "warTies": 0,
    "warWinStreak": 4,
    "badgeUrls": {"large": "https://example.invalid/large.png"},
    "warLeague": {"name": "Crystal League II"},
    "location": {"name": "Indonesia"},
    "labels": [{"name": "Clan Wars"}, {"name": "Donations"}],
    "clanCapital": {"capitalHallLevel": 8},
    "capitalLeague": {"name": "Champion League I"},
    "memberList": [
        {"name": "alpha", "tag": "#A", "trophies": 5100, "donations": 900,
         "donationsReceived": 100, "role": "leader", "townHallLevel": 16},
        {"name": "beta", "tag": "#B", "trophies": 4200, "donations": 0,
         "donationsReceived": 50, "role": "member", "townHallLevel": 14},
    ],
}


class ClanEmbedTests(unittest.TestCase):
    def test_badge_becomes_thumbnail(self):
        embed = build_clan_embed(CLAN)
        self.assertEqual(embed.thumbnail.url, "https://example.invalid/large.png")

    def test_war_record_and_rate_present(self):
        embed = build_clan_embed(CLAN)
        names = [f.name for f in embed.fields]
        self.assertIn("War record", names)
        self.assertIn("War win rate", names)
        record = next(f for f in embed.fields if f.name == "War record")
        self.assertEqual(record.value, "30W – 10L – 0D")

    def test_progress_bars_in_capacity_fields(self):
        embed = build_clan_embed(CLAN)
        members = next(f for f in embed.fields if f.name == "Members")
        self.assertIn("2/50", members.value)
        self.assertIn("█", members.value)

    def test_labels_location_and_league_shown(self):
        names = [f.name for f in build_clan_embed(CLAN).fields]
        self.assertIn("Labels", names)
        self.assertIn("Location", names)
        self.assertIn("War league", names)

    def test_empty_clan_still_builds(self):
        embed = build_clan_embed({})
        self.assertIn("No clan snapshot", embed.description)


WAR = {
    "state": "inWar",
    "teamSize": 2,
    "attacksPerMember": 2,
    "startTime": "20260101T000000.000Z",
    "endTime": "20260102T000000.000Z",
    "battleModifier": "none",
    "clan": {
        "name": "99N", "clanLevel": 12, "stars": 4, "destructionPercentage": 71.5,
        "attacks": 3,
        "badgeUrls": {"medium": "https://example.invalid/medium.png"},
        "members": [
            {"name": "alpha", "mapPosition": 1, "attacks": [
                {"stars": 3, "destructionPercentage": 100},
                {"stars": 1, "destructionPercentage": 60},
            ]},
            {"name": "beta", "mapPosition": 2, "attacks": []},
        ],
    },
    "opponent": {"name": "FOE", "clanLevel": 9, "stars": 2, "destructionPercentage": 45.0,
                 "attacks": 1, "members": [{"name": "x", "mapPosition": 1, "attacks": []}]},
}


class WarEmbedTests(unittest.TestCase):
    def test_lead_line_says_ahead(self):
        embed = build_war_embed(WAR)
        self.assertIn("+2 star(s) ahead", embed.description)

    def test_behind_when_fewer_stars(self):
        war = dict(WAR, clan=dict(WAR["clan"], stars=0))
        self.assertIn("behind", build_war_embed(war).description)

    def test_even_when_tied(self):
        war = dict(WAR, clan=dict(WAR["clan"], stars=2))
        self.assertIn("dead even", build_war_embed(war).description)

    def test_bars_for_stars_and_attacks(self):
        desc = build_war_embed(WAR).description
        self.assertIn("█", desc)
        self.assertIn("3/4", desc)

    def test_idle_members_counted(self):
        embed = build_war_embed(WAR)
        idle = next(f for f in embed.fields if f.name == "No attacks yet")
        self.assertEqual(idle.value, "1 member(s)")

    def test_badge_thumbnail(self):
        embed = build_war_embed(WAR)
        self.assertEqual(embed.thumbnail.url, "https://example.invalid/medium.png")

    def test_attack_summary_zero_attacks_is_safe(self):
        rows = attack_summary({"teamSize": 2, "attacksPerMember": 2})
        self.assertEqual(rows, [])


class WarstatsEmbedTests(unittest.TestCase):
    def test_form_strip_and_margin(self):
        items = [
            {"result": "win", "clan": {"stars": 10}, "opponent": {"stars": 5}},
            {"result": "lose", "clan": {"stars": 4}, "opponent": {"stars": 9}},
        ]
        embed = build_warstats_embed(items)
        form_field = next(f for f in embed.fields if f.name == "Recent form")
        self.assertEqual(form_field.value, "🟩🟥")
        margin = next(f for f in embed.fields if f.name == "Star margin")
        self.assertEqual(margin.value, "+0.0")

    def test_empty_history(self):
        embed = build_warstats_embed([])
        self.assertIn("No finished wars", embed.description)
        # An empty archive must not divide by zero when formatting the bar.
        self.assertIsInstance(embed, discord.Embed)


RAID = {
    "state": "ended",
    "endTime": "20260102T000000.000Z",
    "capitalTotalLoot": 10000,
    "enemyDistrictsDestroyed": 12,
    "totalAttacks": 20,
    "raidsCompleted": 8,
    "offensiveReward": 250,
    "defensiveReward": 90,
    "members": [
        {"name": "alpha", "attacks": 6, "attackLimit": 6, "capitalResourcesLooted": 6000},
        {"name": "beta", "attacks": 3, "attackLimit": 6, "capitalResourcesLooted": 3000},
        {"name": "gamma", "attacks": 0, "attackLimit": 6, "capitalResourcesLooted": 1000},
    ],
}


class RaidEmbedTests(unittest.TestCase):
    def test_top_three_share_shown(self):
        self.assertIn("Top 3 share", build_raid_embed(RAID).description)

    def test_rewards_and_participants(self):
        embed = build_raid_embed(RAID)
        names = [f.name for f in embed.fields]
        self.assertIn("💰 Offensive reward", names)
        self.assertIn("👥 Participants", names)

    def test_top_looters_use_medals(self):
        embed = build_raid_embed(RAID)
        top = next(f for f in embed.fields if f.name == "🏅 Top looters")
        self.assertIn("🥇", top.value)

    def test_member_rows_sorted_by_loot(self):
        rows = raid_member_rows(RAID)
        self.assertEqual([r["name"] for r in rows], ["alpha", "beta", "gamma"])

    def test_absentees_need_the_clan_roster(self):
        # The raid payload itself cannot reveal "never attacked" — only a
        # member missing from a full roster diff can.
        roster = [
            {"name": "alpha", "tag": "#A"},
            {"name": "beta", "tag": "#B"},
            {"name": "gamma", "tag": "#C"},
        ]
        raid = dict(RAID)
        raid["members"] = [
            {"name": "alpha", "tag": "#A", "attacks": 6, "capitalResourcesLooted": 6000},
            {"name": "beta", "tag": "#B", "attacks": 3, "capitalResourcesLooted": 3000},
        ]
        absent = raid_absentees(raid, roster)
        self.assertEqual([r["name"] for r in absent], ["gamma"])

    def test_absentees_without_roster_lists_zero_attack_rows(self):
        absent = raid_absentees(RAID, None)
        self.assertEqual([r["name"] for r in absent], ["gamma"])

    def test_empty_raid_is_safe(self):
        embed = build_raid_embed({"state": "ended", "members": []})
        self.assertIsInstance(embed.description, str)


class LogFileTests(unittest.TestCase):
    def test_setup_writes_to_the_log_file(self):
        from bot.logging_setup import log_dir, setup_logging

        setup_logging()
        logger = logging.getLogger("99n.test.sink")
        logger.setLevel(logging.INFO)
        marker = "log-sink-marker-0042"
        logger.info(marker)
        for handler in logging.getLogger().handlers:
            handler.flush()

        path = log_dir() / "bot.log"
        if not path.exists():  # read-only checkout: file logging is optional
            self.skipTest("file logging disabled in this environment")
        self.assertIn(marker, path.read_text(encoding="utf-8", errors="replace"))

    def test_setup_is_idempotent(self):
        from bot.logging_setup import setup_logging

        setup_logging()
        before = len(logging.getLogger().handlers)
        setup_logging()
        self.assertEqual(len(logging.getLogger().handlers), before)


class FakeChannel:
    def __init__(self, sent, fail=False):
        self.sent = sent
        self.fail = fail

    async def send(self, content):
        if self.fail:
            raise RuntimeError("discord is down")
        self.sent.append(content)


class FakeBot:
    """Minimal stand-in for the two members the handler touches.

    Deliberately has no ``loop`` attribute: ``discord.Client.loop`` raises
    outside a running loop, so the handler must not depend on it.
    """

    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, cid):
        return self.channel


def record(msg, level=logging.INFO):
    return logging.LogRecord("x", level, "f", 1, msg, None, None)


class DiscordLogHandlerTests(unittest.TestCase):
    def test_inert_until_attached(self):
        handler = DiscordLogHandler(123)
        # Emitting before attach must not raise; the file log still has it.
        handler.handle(record("hello"))
        self.assertEqual(len(handler._buffer), 0)

    def test_records_reach_the_channel(self):
        sent = []
        bot = FakeBot(FakeChannel(sent))
        handler = DiscordLogHandler(123)

        async def pump():
            handler.attach(bot)
            handler.handle(record("war ended 10-4"))
            for _ in range(50):
                await asyncio.sleep(0)
                if sent:
                    break

        asyncio.run(pump())
        self.assertTrue(sent, "the handler must post to the channel")
        joined = "\n".join(sent)
        self.assertIn("war ended 10-4", joined)
        self.assertTrue(joined.startswith("```"), "log content must be code-fenced")

    def test_bursts_are_batched_and_drained_completely(self):
        sent = []
        bot = FakeBot(FakeChannel(sent))
        handler = DiscordLogHandler(123)

        async def pump():
            handler.attach(bot)
            for i in range(25):
                handler.handle(record(f"line {i}"))
            for _ in range(200):
                await asyncio.sleep(0)
                if handler._buffer or handler._pending:
                    continue
                break

        asyncio.run(pump())
        joined = "\n".join(sent)
        for i in range(25):
            self.assertIn(f"line {i}", joined, f"line {i} was lost")
        self.assertTrue(handler._buffer.maxlen == 200)

    def test_send_failure_is_swallowed(self):
        bot = FakeBot(FakeChannel([], fail=True))
        handler = DiscordLogHandler(123)

        async def pump():
            handler.attach(bot)
            handler.handle(record("boom", logging.ERROR))
            for _ in range(20):
                await asyncio.sleep(0)

        # A Discord outage while logging must not propagate to the caller.
        asyncio.run(pump())

    def test_missing_channel_is_tolerated(self):
        bot = FakeBot(None)
        handler = DiscordLogHandler(999)

        async def pump():
            handler.attach(bot)
            handler.handle(record("x"))
            for _ in range(10):
                await asyncio.sleep(0)

        asyncio.run(pump())

    def test_attach_outside_a_running_loop_is_reported(self):
        # attach() is documented as async-only; calling it from sync code must
        # raise rather than silently bind a dead loop.
        handler = DiscordLogHandler(123)
        with self.assertRaises(RuntimeError):
            handler.attach(FakeBot(None))

    def test_attach_discord_log_is_opt_in(self):
        from bot.discord_log import attach_discord_log

        self.assertIsNone(attach_discord_log("", None))
        self.assertIsNone(attach_discord_log(None, None))


class ConfigSummaryTests(unittest.TestCase):
    def test_summary_and_table_still_build(self):
        from bot.config_store import ConfigStore

        store = ConfigStore(tempfile.mkdtemp())
        config = store.get(100)
        self.assertIn("Timezone", build_config_summary(config))
        rows = build_notif_table(config)
        self.assertTrue(all("key" in r for r in rows))


class FakeCtx:
    def __init__(self, bot=None):
        self.sent = []
        self.bot = bot

    async def send(self, content=None, embed=None):
        self.sent.append((content, embed))
        return None


class LogCommandTests(unittest.TestCase):
    def test_logs_command_is_registered(self):
        from bot.cogs.admin import AdminCog

        names = {c.name for c in AdminCog.__cog_commands__}
        self.assertIn("logs", names)
        self.assertIn("freshness", names)

    def _cog(self):
        from bot.cogs.admin import AdminCog

        class Bot:
            pass

        return AdminCog(Bot())

    def setUp(self):
        # Redirect the log dir so the fixtures below own the file they assert
        # on instead of appending junk to the checkout's real logs/bot.log.
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("BOT_LOG_DIR")
        os.environ["BOT_LOG_DIR"] = self._tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("BOT_LOG_DIR", None)
        else:
            os.environ["BOT_LOG_DIR"] = self._old

    def _write_log(self, text):
        path = Path(self._tmp) / "bot.log"
        path.write_text(text, encoding="utf-8")
        return path

    FIXTURE = (
        "2026-01-01 00:00:00 INFO    99n.a  hello\n"
        "2026-01-01 00:00:01 ERROR   99n.b  boom\n"
    )

    def test_logs_shows_recent_lines(self):
        cog = self._cog()
        self._write_log(self.FIXTURE)
        ctx = FakeCtx()
        asyncio.run(cog.logs.callback(cog, ctx, 5, None))
        _content, embed = ctx.sent[-1]
        self.assertIn("boom", embed.description)
        self.assertIn("```", embed.description)

    def test_logs_level_filter(self):
        cog = self._cog()
        self._write_log(self.FIXTURE)
        ctx = FakeCtx()
        asyncio.run(cog.logs.callback(cog, ctx, 10, "error"))
        _content, embed = ctx.sent[-1]
        self.assertIn("boom", embed.description)
        self.assertNotIn("hello", embed.description)

    def test_logs_missing_file_is_reported_not_raised(self):
        cog = self._cog()
        ctx = FakeCtx()
        asyncio.run(cog.logs.callback(cog, ctx, 10, None))
        content, _embed = ctx.sent[-1]
        self.assertIn("No log file yet", content)


if __name__ == "__main__":
    unittest.main()
