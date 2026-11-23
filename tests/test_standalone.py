"""A bare checkout must run without the 99N dashboard beside it."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from bot import bot_config
from bot.snapshots import SnapshotReader

ROOT = Path(bot_config.BASE_DIR)


class TestStandalone(unittest.TestCase):
    def test_assets_are_committed(self):
        halls = sorted((ROOT / "assets").glob("Town_Hall*.webp"))
        self.assertEqual(len(halls), 19, halls)
        self.assertTrue((ROOT / "assets" / "Town_Hall18.webp").exists())

    def test_example_points_inside_the_repo(self):
        values = {}
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
            if line.startswith(("DATA_DIR=", "ASSET_DIR=")):
                key, _, value = line.partition("=")
                values[key] = value
        self.assertEqual(values, {"DATA_DIR": "./data", "ASSET_DIR": "./assets"})
        for key, value in values.items():
            self.assertFalse(Path(value).is_absolute(), key)

    def test_defaults_need_no_env_file(self):
        """A fresh clone has no .env; the defaults must still find the data."""
        code = (
            "import os;"
            "os.environ.pop('DATA_DIR', None);"
            "os.environ.pop('ASSET_DIR', None);"
            "from bot import bot_config as c;"
            "print(c.DATA_DIR);print(c.ASSET_DIR);"
            "print(c.DATA_DIR.exists(), c.ASSET_DIR.exists())"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            cwd="/tmp",
            env={k: v for k, v in os.environ.items()
                 if k not in ("DATA_DIR", "ASSET_DIR")} | {"PYTHONPATH": str(ROOT)},
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.strip().splitlines()
        self.assertEqual(lines[0], str(ROOT / "data"))
        self.assertEqual(lines[1], str(ROOT / "assets"))
        self.assertEqual(lines[2], "True True")

    def test_runs_from_an_unrelated_cwd(self):
        """load_dotenv() and _path_env() must both ignore the working directory."""
        code = (
            "from bot import bot_config;"
            "from bot.snapshots import SnapshotReader;"
            "r = SnapshotReader(str(bot_config.DATA_DIR));"
            "print(bot_config.DATA_DIR);"
            "print(len(r.members()), len(r.players()))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            cwd="/tmp",
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.strip().splitlines()
        self.assertEqual(lines[0], str(ROOT / "data"))
        self.assertEqual(lines[1], "50 50")

    def test_snapshots_read_from_the_copied_data(self):
        reader = SnapshotReader(str(ROOT / "data"))
        self.assertEqual(len(reader.members()), 50)
        self.assertEqual(len(reader.players()), 50)
        self.assertTrue(reader.war().get("state"))
        index = json.loads((ROOT / "data" / "clan_stats_index.json").read_text())
        self.assertTrue(index)
        self.assertTrue((ROOT / "data" / "clan_stats" / index[0]).exists())

    def test_an_empty_prefix_requests_no_privileged_intents(self):
        """Slash-only means no Message Content intent, so the bot starts with
        no Developer Portal toggles. BOT_PREFIX is forced empty because
        bot_config reads the developer's own .env, which may set a prefix."""
        code = (
            "import os; os.environ['BOT_PREFIX'] = '';"
            "from bot import bot_config;"
            "assert bot_config.BOT_PREFIX == '', repr(bot_config.BOT_PREFIX);"
            "import importlib.util as u;"
            "s = u.spec_from_file_location('entrybot', r'" + str(ROOT / "bot.py") + "');"
            "m = u.module_from_spec(s); s.loader.exec_module(m);"
            "i = m.NinetyNineBot().intents;"
            "print(i.members, i.presences, i.message_content)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            env={k: v for k, v in os.environ.items() if k != "BOT_PREFIX"}
            | {"PYTHONPATH": str(ROOT)},
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "False False False")

    def test_prefix_opt_in_restores_message_content(self):
        """BOT_PREFIX set means the user knows they must enable the intent."""
        code = (
            "import os; os.environ['BOT_PREFIX'] = '!';"
            "import importlib.util as u;"
            "s = u.spec_from_file_location('entrybot', r'" + str(ROOT / "bot.py") + "');"
            "m = u.module_from_spec(s); s.loader.exec_module(m);"
            "print(m.NinetyNineBot().intents.message_content)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "True")


if __name__ == "__main__":
    unittest.main()
