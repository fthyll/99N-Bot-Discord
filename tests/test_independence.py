"""The bot must not depend on the 99N scraper checkout being present.

Every one of these checks is a thing that silently degraded the bot before:
importing the scraper package through sys.path meant a missing sibling checkout
turned six notification builders into empty lists.
"""

import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot import bot_config
from bot.events import NOTIFY_EVENTS

ROOT = Path(bot_config.BASE_DIR)
STDLIB_OK = {
    "asyncio", "collections", "copy", "datetime", "json", "logging", "os", "sys",
    "zoneinfo", "pathlib", "re", "time", "urllib", "threading",
}


def _modules():
    files = sorted((ROOT / "bot").rglob("*.py")) + [ROOT / "bot.py"]
    return [f for f in files if "__pycache__" not in str(f)]


class TestNoSiblingCheckout(unittest.TestCase):
    def test_no_sys_path_manipulation(self):
        offenders = []
        for path in _modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("path", "insert"):
                    if isinstance(node.value, ast.Name) and node.value.id == "sys":
                        offenders.append(path.name)
        self.assertEqual(offenders, [], "sys.path is modified; importers break on a bare clone")

    def test_no_reference_to_the_99n_checkout(self):
        offenders = []
        for path in _modules():
            text = path.read_text(encoding="utf-8")
            for needle in ("../99N", "99N/scrapers", "from notifier import"):
                if needle in text and "bot_config.py" not in path.name:
                    offenders.append(f"{path.name}: {needle}")
        self.assertEqual(offenders, [])

    def test_third_party_imports_are_discord_and_dotenv_only(self):
        allowed = STDLIB_OK | {"discord", "dotenv", "bot"}
        offenders = []
        for path in _modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module.split(".")[0]]
                for name in names:
                    if name not in allowed:
                        offenders.append(f"{path.name}: {name}")
        self.assertEqual(offenders, [])

    def test_vendored_embeds_are_present_and_importless(self):
        path = ROOT / "bot" / "notifier_embeds.py"
        self.assertTrue(path.exists())
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [], "vendored file must stay dependency-free")
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        for builder in ("war_preview", "war_result", "raid_start", "raid_summary",
                        "membership_change", "donation_reset"):
            self.assertIn(builder, names)

    def test_every_event_still_produces_an_embed(self):
        """All events must render from a snapshot alone.

        Each trigger needs its own snapshot state (a war cannot be in
        preparation and ended at once), so every scenario is fed in turn and
        the union of fired keys is checked.
        """
        now = datetime.now(timezone.utc)
        base = {"war": {}, "raid": {}, "clan": {}, "meta": {},
                "reader": None, "now": now, "prev": {}}
        live_end = (now + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S.000Z")
        scenarios = [
            ({}, {}),
            ({"war": {"state": "warEnded", "startTime": "W1", "endTime": "E1",
                      "teamSize": 15, "attacksPerMember": 2,
                      "clan": {"name": "99N", "stars": 44, "destructionPercentage": 62.5,
                               "attacks": 17,
                               "members": [{"tag": "#A", "name": "A", "attacks": [],
                                            "opponentAttacks": 1}]},
                      "opponent": {"name": "Foe", "stars": 40,
                                   "destructionPercentage": 71.2, "attacks": 19,
                                   "members": []}}}, {}),
            ({"war": {"state": "preparation", "startTime": "W2", "teamSize": 15,
                      "attacksPerMember": 2, "clan": {"name": "99N", "members": []},
                      "opponent": {"name": "Foe", "members": []}}}, {}),
            ({"war": {"state": "inWar", "startTime": "W3", "endTime": live_end,
                      "teamSize": 15, "attacksPerMember": 2,
                      "clan": {"name": "99N", "stars": 0, "destructionPercentage": 0.0,
                               "attacks": 1,
                               "members": [{"tag": "#A", "name": "A", "attacks": [{}],
                                            "opponentAttacks": 1}]},
                      "opponent": {"name": "Foe", "stars": 0, "attacks": 0,
                                   "destructionPercentage": 0.0, "members": []}}}, {}),
            ({"raid": {"state": "ongoing", "startTime": "R1", "endTime": "E1",
                       "capitalTotalLoot": 100, "totalAttacks": 3, "members": []}}, {}),
            ({"raid": {"state": "ended", "startTime": "R1", "endTime": "E1",
                       "capitalTotalLoot": 100, "totalAttacks": 3, "members": []}},
             {"raid": {"state": "ongoing"}}),
            ({"clan": {"memberList": [{"tag": "#A", "name": "A", "donations": 0}]}}, {}),
            ({"clan": {"memberList": [{"tag": "#A", "name": "A", "donations": 5}]}},
             {"clan": {"memberTags": ["#A", "#GONE"]}}),
            ({"meta": {"cwl": {"state": "inWar", "season": "2026-11"}}},
             {"cwl": {"state": "preparation"}}),
            ({"clan": {"memberList": [{"tag": "#A", "name": "A", "donations": 5}]}},
             {"clan": {"donations": {"total": 9000, "received": 200}}}),
        ]

        # raid.reminder only speaks inside the last 12h with idle members, and
        # clan.donation_weekly only on Monday 05:00 UTC — their own clocks are
        # part of the condition, so they get scenarios with a fitting `now`.
        monday_5am = now.replace(hour=5, minute=0, second=0, microsecond=0)
        monday_5am -= timedelta(days=monday_5am.weekday())
        raid_ending = {
            "raid": {"state": "ongoing", "startTime": "R2",
                     "endTime": (now + timedelta(hours=2)).strftime("%Y%m%dT%H%M%S.000Z"),
                     "capitalTotalLoot": 100, "totalAttacks": 1,
                     "members": [{"tag": "#A", "name": "A", "attacks": 0,
                                  "attackLimit": 5, "capitalResourcesLooted": 0}]},
        }
        scenarios += [
            (raid_ending, {}),
            ({"clan": {"memberList": [{"tag": "#A", "name": "A", "donations": 7}]}}, {}),
        ]

        hits, errors = set(), {}
        for payload, prev in scenarios:
            ctx = dict(base)
            ctx.update(payload)
            for key, trigger in NOTIFY_EVENTS.items():
                try:
                    if trigger(ctx, prev):
                        hits.add(key)
                except Exception as exc:
                    errors[key] = repr(exc)

        # Re-run the two clock-bound triggers with a matching clock.
        ctx = dict(base, now=monday_5am,
                   clan={"memberList": [{"tag": "#A", "name": "A", "donations": 7}]})
        for key in ("clan.donation_weekly",):
            if NOTIFY_EVENTS[key](ctx, {}):
                hits.add(key)

        self.assertEqual(errors, {}, "triggers crashed")
        # system.stale needs a real reader with aged stamps; everything else
        # must be reachable from a snapshot alone.
        self.assertEqual(set(NOTIFY_EVENTS) - {"system.stale"} - hits, set())


if __name__ == "__main__":
    unittest.main()
