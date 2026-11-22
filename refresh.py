#!/usr/bin/env python3
"""Pull the newest snapshots straight from the 99N repo over HTTPS.

The bot reads files, so it has never needed the Supercell API — but refreshing
`data/` used to mean having a sibling 99N checkout to copy from. This script
removes that: it fetches the indices, then only the snapshot each index points
at, so a refresh costs ~0.8 MB instead of the whole 11 MB archive.

Uses only the standard library, so it runs before `pip install -r`.

    python3 refresh.py              # refresh data/ from main
    python3 refresh.py --assets     # also refresh assets/
    REFRESH_BRANCH=dev python3 refresh.py
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

REPO = os.getenv("REFRESH_REPO", "fthyll/99N")
BRANCH = os.getenv("REFRESH_BRANCH", "main")
BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Folder -> index file. The index lists snapshot filenames.
SNAPSHOT_FOLDERS = ("clan_stats", "player_stats", "war_stats", "raid_stats")
# Newest-first indices: clan_stats, player_stats. Oldest-first: war, raid.
NEWEST_FIRST = frozenset({"clan_stats", "player_stats"})
PLAIN_FILES = (
    "meta.json",
    "sync_war.json",
    "sync_raid.json",
    "player_trends.json",
    "warlog_stats/warlog.json",
)
TOWN_HALLS = range(1, 20)


def fetch(path):
    url = f"{BASE}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        print(f"  ! {path}: HTTP {exc.code}")
    except urllib.error.URLError as exc:
        print(f"  ! {path}: {exc.reason}")
    return None


def write(rel_path, payload):
    target = os.path.join(DATA_DIR, rel_path)
    os.makedirs(os.path.dirname(target) or DATA_DIR, exist_ok=True)
    with open(target, "wb") as f:
        f.write(payload)
    return len(payload)


def refresh_data():
    written = 0
    total = 0

    for folder in SNAPSHOT_FOLDERS:
        index_name = f"{folder}_index.json"
        raw = fetch(f"data/{index_name}")
        if raw is None:
            continue
        total += write(index_name, raw)
        written += 1

        names = json.loads(raw)
        if not isinstance(names, list) or not names:
            print(f"  ! {index_name}: not a list")
            continue
        newest = names[0] if folder in NEWEST_FIRST else names[-1]
        raw = fetch(f"data/{folder}/{newest}")
        if raw is None:
            continue
        total += write(os.path.join(folder, newest), raw)
        written += 1
        print(f"  {folder}: {newest}")

    for rel in PLAIN_FILES:
        raw = fetch(f"data/{rel}")
        if raw is None:
            continue
        total += write(rel, raw)
        written += 1
        print(f"  {rel}")

    return written, total


def refresh_assets():
    written = 0
    total = 0
    os.makedirs(ASSET_DIR, exist_ok=True)
    for level in TOWN_HALLS:
        name = f"Town_Hall{level}.webp"
        raw = fetch(f"assets/{name}")
        if raw is None:
            continue
        with open(os.path.join(ASSET_DIR, name), "wb") as f:
            f.write(raw)
        total += len(raw)
        written += 1
    return written, total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", action="store_true",
                        help="also refresh assets/Town_Hall*.webp")
    args = parser.parse_args()

    print(f"Refreshing from {BASE}")
    try:
        files, size = refresh_data()
    except json.JSONDecodeError as exc:
        print(f"Bad index from the remote: {exc}")
        return 1
    print(f"data/: {files} files, {size / 1024:.1f} KB")

    if args.assets:
        files, size = refresh_assets()
        print(f"assets/: {files} files, {size / 1024:.1f} KB")

    print("Done. Restart the bot to pick the new snapshots up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
