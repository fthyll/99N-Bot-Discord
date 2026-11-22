import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot import bot_config


class TestPathEnv(unittest.TestCase):
    """Relative DATA_DIR/ASSET_DIR must resolve against the bot, not the cwd."""

    def test_relative_resolves_against_base_dir(self):
        with mock.patch.dict(os.environ, {"DATA_DIR": "../99N/data"}):
            got = bot_config._path_env("DATA_DIR", Path("/nope"))
        self.assertTrue(got.is_absolute())
        self.assertEqual(got, (bot_config.BASE_DIR / "../99N/data").resolve())

    def test_absolute_is_kept(self):
        with mock.patch.dict(os.environ, {"DATA_DIR": "/srv/99N/data"}):
            self.assertEqual(str(bot_config._path_env("DATA_DIR", Path("/nope"))), "/srv/99N/data")

    def test_empty_falls_back_to_default(self):
        with mock.patch.dict(os.environ, {"DATA_DIR": ""}):
            self.assertEqual(str(bot_config._path_env("DATA_DIR", Path("/d"))), "/d")

    def test_shipped_example_points_at_a_real_checkout(self):
        """The .env.example values must resolve to the sibling 99N checkout."""
        example = Path(bot_config.BASE_DIR) / ".env.example"
        values = {}
        for line in example.read_text(encoding="utf-8").splitlines():
            if line.startswith(("DATA_DIR=", "ASSET_DIR=")):
                key, _, value = line.partition("=")
                values[key] = value
        self.assertEqual(sorted(values), ["ASSET_DIR", "DATA_DIR"])
        with mock.patch.dict(os.environ, values):
            data = bot_config._path_env("DATA_DIR", Path("/nope"))
            assets = bot_config._path_env("ASSET_DIR", Path("/nope"))
        self.assertTrue(data.exists(), data)
        self.assertTrue(assets.exists(), assets)
        self.assertTrue((assets / "Town_Hall18.webp").exists())


if __name__ == "__main__":
    unittest.main()
