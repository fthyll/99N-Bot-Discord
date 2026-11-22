import json
import os
import tempfile
import unittest

from bot.config_store import ConfigStore


class TestConfigStore(unittest.TestCase):
    def test_defaults_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            s = ConfigStore(root=d)
            cfg = s.get(123)
            self.assertTrue(cfg["events"]["war.result"]["enabled"])
            self.assertIsNone(cfg["events"]["war.result"]["channel_id"])
            self.assertEqual(cfg["quiet_hours"]["start"], "23:00")
            self.assertEqual(cfg["quiet_hours"]["end"], "07:00")

    def test_set_dotted_key_persists(self):
        with tempfile.TemporaryDirectory() as d:
            s = ConfigStore(root=d)
            s.set(123, "events.war.result.enabled", False)
            cfg = s.get(123)
            self.assertFalse(cfg["events"]["war.result"]["enabled"])
            with open(os.path.join(d, "123.json")) as f:
                saved = json.load(f)
            self.assertFalse(saved["events"]["war.result"]["enabled"])

    def test_set_channel_for_all(self):
        with tempfile.TemporaryDirectory() as d:
            s = ConfigStore(root=d)
            s.set_channel(123, "all", 99999)
            cfg = s.get(123)
            self.assertEqual(cfg["events"]["war.result"]["channel_id"], 99999)
            self.assertEqual(cfg["events"]["raid.summary"]["channel_id"], 99999)

    def test_quiet_hours_check(self):
        with tempfile.TemporaryDirectory() as d:
            s = ConfigStore(root=d)
            from datetime import time
            self.assertTrue(s.in_quiet_hours(123, time(0, 30)))
            self.assertTrue(s.in_quiet_hours(123, time(6, 59)))
            self.assertFalse(s.in_quiet_hours(123, time(7, 0)))
            self.assertFalse(s.in_quiet_hours(123, time(14, 0)))
            self.assertTrue(s.in_quiet_hours(123, time(23, 15)))


if __name__ == "__main__":
    unittest.main()
