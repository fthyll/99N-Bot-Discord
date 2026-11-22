import tempfile
import unittest

from bot.cogs.admin import build_config_summary, build_notif_table
from bot.config_store import ConfigStore
from bot.events import event_keys


class TestAdminCog(unittest.TestCase):
    def test_build_notif_table(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = ConfigStore(root=d).get(1)
        rows = build_notif_table(cfg)
        self.assertEqual(len(rows), len(event_keys()))
        self.assertTrue(all("key" in r and "enabled" in r for r in rows))

    def test_build_config_summary(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = ConfigStore(root=d).get(1)
        text = build_config_summary(cfg)
        self.assertIn("Quiet hours", text)
        self.assertIn("Enabled events", text)


if __name__ == "__main__":
    unittest.main()
