"""Tests for the event icon pack and its use in notifications."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

import discord

from bot import notifier
from bot.config_store import ConfigStore
from bot.event_icons import EVENT_ICONS, icon_path


def _embed(title="Test"):
    return discord.Embed(title=title, description="body", color=0x5865F2)


class TestIconPack(unittest.TestCase):
    """Every manifest entry must be a real, valid WebP file."""

    def test_every_group_has_an_entry(self):
        for group in ("war", "raid", "clan", "system"):
            self.assertIn(group, EVENT_ICONS)

    def test_every_entry_exists_and_is_webp(self):
        for group, rel in EVENT_ICONS.items():
            path = icon_path(group)
            self.assertIsNotNone(path, f"{group}: {rel} missing on disk")
            with open(path, "rb") as f:
                head = f.read(12)
            # WebP = RIFF at 0, WEBP at offset 8.
            self.assertTrue(head[:4] == b"RIFF" and head[8:12] == b"WEBP", group)

    def test_unknown_group_returns_none(self):
        self.assertIsNone(icon_path("nope"))

    def test_icon_bytes_are_distinct(self):
        # Two identical files would mean one silently fell back to the other.
        paths = [icon_path(g) for g in EVENT_ICONS]
        self.assertTrue(all(p is not None for p in paths))
        blobs = {Path(p).read_bytes() for p in paths}
        self.assertEqual(len(blobs), len(paths))


class TestNotifierAttachesIcons(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(root=self.tmp.name)
        self.store.set_channel(1, "all", 42)

    def tearDown(self):
        self.tmp.cleanup()

    def _run_tick(self, bot, events):
        """Drive one Dispatcher tick with a stubbed due_events."""
        config_store = self.store
        dispatcher = notifier.Dispatcher(
            bot, reader=MagicMock(), config_store=config_store, state_store=MagicMock()
        )
        dispatcher._guild_ids = lambda: [1]
        dispatcher._in_quiet_hours = lambda guild_id, now: False
        original = notifier.due_events
        notifier.due_events = lambda *a, **k: events
        try:
            import asyncio

            return asyncio.run(dispatcher.tick())
        finally:
            notifier.due_events = original

    def test_icon_file_rides_the_first_message(self):
        embed = _embed()
        sent = []

        async def fake_send(content=None, embed=None, file=None):
            sent.append((content, embed, file))

        channel = MagicMock()
        channel.send = fake_send
        bot = MagicMock()
        bot.get_channel = lambda cid: channel

        self._run_tick(bot, [("war.result", [embed])])
        self.assertEqual(len(sent), 1)
        content, embed_sent, file = sent[0]
        self.assertIsNotNone(file, "war notification must carry the group icon")
        self.assertTrue(file.filename.endswith(".webp"))
        # The embed must point at the attachment for the art to render.
        self.assertIn("attachment://", embed_sent.thumbnail.url)

    def test_missing_pack_sends_without_art(self):
        embed = _embed()
        sent = []

        async def fake_send(content=None, embed=None, file=None):
            sent.append((content, embed, file))

        channel = MagicMock()
        channel.send = fake_send
        bot = MagicMock()
        bot.get_channel = lambda cid: channel

        original = notifier._group_icon_path
        notifier._group_icon_path = lambda group: None
        try:
            self._run_tick(bot, [("war.result", [embed])])
        finally:
            notifier._group_icon_path = original
        self.assertEqual(len(sent), 1)
        self.assertIsNone(sent[0][2], "no pack means no file, not a crash")
        # Embed.thumbnail is an EmbedProxy, always truthy; url is the real test.
        self.assertIsNone(sent[0][1].thumbnail.url)

    def test_icon_not_attached_when_embed_has_its_own(self):
        """Player-card style embeds set their own thumbnail; do not clobber it."""
        embed = _embed()
        embed.set_thumbnail(url="attachment://Town_Hall14.webp")
        sent = []

        async def fake_send(content=None, embed=None, file=None):
            sent.append((content, embed, file))

        channel = MagicMock()
        channel.send = fake_send
        bot = MagicMock()
        bot.get_channel = lambda cid: channel

        self._run_tick(bot, [("war.result", [embed])])
        self.assertIn("Town_Hall14.webp", sent[0][1].thumbnail.url)


if __name__ == "__main__":
    unittest.main()
