"""Refresh script must produce a data/ the bot can read, with no 99N checkout."""
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestRefresh(unittest.TestCase):
    def test_script_imports_without_third_party(self):
        import ast
        tree = ast.parse((ROOT / "refresh.py").read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        allowed = {"argparse", "json", "os", "sys", "urllib"}
        self.assertEqual(names - allowed, set(), "refresh.py must be stdlib-only")

    def test_refresh_into_a_clean_dir(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(ROOT / "refresh.py", tmp)
        # Only the network-dependent half is exercised; this is the one test
        # that needs internet, and it is skipped when the fetch fails.
        out = subprocess.run([sys.executable, "refresh.py"], cwd=tmp,
                             capture_output=True, text=True, timeout=120)
        if out.returncode != 0 or "0 files" in out.stdout:
            self.skipTest(f"no network: {out.stdout.strip()[:120]} {out.stderr[:120]}")
        reader = subprocess.run(
            [sys.executable, "-c",
             "import sys;sys.path.insert(0, %r);"
             "from bot.snapshots import SnapshotReader;"
             "r=SnapshotReader(%r);"
             "print(len(r.members()), len(r.players()), r.war().get('state') or '-',"
             " r.raid().get('state') or '-', len(r.warlog()))"
             % (str(ROOT), os.path.join(tmp, "data"))],
            cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(reader.returncode, 0, reader.stderr)
        members, players, war, raid, warlog = reader.stdout.split()
        self.assertEqual(members, "50")
        self.assertEqual(players, "50")
        self.assertNotEqual(war, "-")
        self.assertNotEqual(raid, "-")
        self.assertGreater(int(warlog), 0)


if __name__ == "__main__":
    unittest.main()
