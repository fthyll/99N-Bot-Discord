# Changelog

All notable changes to the **99N Bot Discord** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-11-23

### Added
- **`/notif panel`**: one message to configure everything. A dropdown lists every
  notification with its current state and a plain description of when it fires,
  **Turn on**/**Turn off** buttons act on the selection (or on everything via the
  *All notifications* entry), and Discord's own **channel** and **role** pickers
  replace typing snowflakes by hand. The embed re-renders from the config file on
  every interaction, so it can never show a change that was not saved.
- **`/notif preset <profile> [#channel]`**: apply a whole profile at once —
  `essential`, `war-only`, `raid-only`, or `all` — routed to one channel.
- **Autocomplete on every event argument**: `/notif set`, `/notif channel`,
  `/notif ping` and `/notif test` suggest events by human label, so typing
  `reminder` finds both `war.attack_reminder` and `raid.reminder`. `/notif set
  state` suggests on/off; `/notif preset profile` suggests the profiles.
- **Human labels and one-line help** for all 14 events (`bot/events.py`),
  used by the panel, `/notif list`, and autocomplete.
- **Notification icons**: every notification embed now carries a WebP thumbnail
  for its group (War → Barbarian King, Raid → Goblin, Clan → Archer Queen,
  System → Lightning Spell). Art from [coc.guide](https://coc.guide) game files,
  converted locally and committed to `assets/events/`; `scripts/fetch_event_icons.py`
  regenerates the pack and its manifest, and a missing pack sends without art
  rather than failing.
- **`/notif set all`** and `event=all` in autocomplete: one action for everything.
- Verification scripts: `panel_probe.py` (panel structure and persistence),
  `command_probe.py` (subcommand registration and autocomplete bindings),
  `preview_panel.py` (renders `panel_preview.md`).

### Changed
- `/notif list` is grouped (War/Raid/Clan/CWL/System) and uses human labels plus
  real `<#channel>`/`<@&role>` mentions instead of raw ids.
- `/notif channel` now accepts `all`, matching `/notif set` and `/notif ping`.

### Fixed
- `@ui.select` defaults to a plain `Select`, so the channel and role pickers
  rendered as empty dropdowns with no options; they now pass `cls=ChannelSelect`
  / `cls=RoleSelect`.
- The panel's *All notifications* entry used `__all__` where `ConfigStore`
  expects `all`, raising `KeyError` on the first channel selection.
- `clan.donation_weekly` posted an empty leaderboard when no clan snapshot was
  available, breaking the "every trigger stays quiet without data" contract.
- Startup warned that the privileged message-content intent was missing, because
  `command_prefix` fell back to `"!"` while the intent was off. An empty prefix
  list makes the slash-only mode explicit.
- The channel and role pickers stayed clickable before a notification was
  chosen, so the only possible outcome was an error after the user had already
  made a choice. They are disabled until a target exists, like the action
  buttons.

## [1.1.0] - 2026-11-23

### Added
- **Live Clash of Clans API (`bot/coc_api.py`)**:
  - Stdlib `urllib` client with a TTL cache (`COC_CACHE_SECONDS`).
  - `WarmCache` (`bot/offload.py`) refreshes in a background thread so no slash command ever waits on a socket.
  - Graceful fallback: any API failure (403 token/IP, 5xx, timeout) serves the committed snapshot and records the reason in `last_errors` for `/freshness`, instead of raising into a Discord command.
- **Structured logging (`bot/logging_setup.py`, `bot/discord_log.py`)**:
  - Console plus a rotating `logs/bot.log` (5 MB × 3 backups), stdlib only, no new dependency.
  - `LOG_LEVEL` and `BOT_LOG_DIR` environment overrides; `discord.py` internals kept at WARNING.
  - Optional `LOG_CHANNEL_ID` mirrors log lines into a Discord channel; the handler posts from a thread-safe deque via `call_soon_threadsafe`, drops rather than raises, and is opt-in so the bot never posts its own logs uninvited.
- **`/logs [lines] [level]`**: tails `logs/bot.log` from Discord, reading the file in an executor so a large log cannot stall the event loop.
- **Richer embeds**: official CoC clan/league badges as thumbnails, Unicode progress bars, percentages and ratios (war win-rate, raid top-3 share, turnout), win-form strips (`🟩🟥🟨`), and 🥇🥈🥉 ranking medals. `/member` adds exp level, net donations, war/attack/defense wins, and league tier when the profile API provides them.
- **Verification scripts**: `scripts/preview_embeds.py` renders every embed from real data, `scripts/boot_probe.py` exercises startup without a token, `scripts/live_check.py` starts the real bot and asserts it reaches ready.

### Changed
- **Slash-only by default**: `BOT_PREFIX` ships empty and `intents.message_content` is only requested when a prefix is set, removing the need to toggle a privileged intent in the Discord Developer Portal.
- `/freshness` is mode-aware: it reports live-cache state and API errors in live mode, snapshot age otherwise.
- Clan war record now includes draws, and war win-rate is a percentage with a bar.

### Fixed
- Raid attack display showed `6/5`: `attacks` counts bonus attacks, so capacity must be `attackLimit + bonusAttackLimit`.
- Raid "no attacks" could never be non-zero, because the raid payload only lists members who attacked; it now diffs against the clan roster.
- `getattr(channel, "name", channel.id)` evaluated `channel.id` eagerly and raised on a channel without an `id`, marking a successful notification send as failed.
- `discord.Client.loop` raises `AttributeError` outside a running loop; the log handler and `/logs` now capture the loop with `asyncio.get_running_loop()`.

## [1.0.0] - 2026-11-22

### Added
- **Core Architecture & Runner**:
  - `bot.py` entrypoint supporting both prefix (`!`) and Discord Application Slash commands.
  - Runtime configuration module (`bot.bot_config`) with environment variable parsing and fallback paths to sibling `../99N` project data & assets.
  - Town Hall WebP image locator (`Town_Hall1.webp` to `Town_Hall19.webp`) for inline embed attachments.
  - Multi-cog modular structure: Clan, Player, War, Raid, and Admin.

- **Snapshot Reader (`bot.snapshots`)**:
  - Zero-API snapshot reader parsing local JSON dumps in `data/`:
    - `clan_stats/members_*.json` and `clan_stats_index.json`
    - `war_stats/war_*.json` and `war_stats_index.json`
    - `raid_stats/raid_*.json` and `raid_stats_index.json`
    - `player_stats/players_*.json` and `player_trends.json`
    - `meta.json`, `sync_war.json`, and `sync_raid.json`
  - Helper functions for finding latest entries, calculating snapshot freshness, and member lookups.

- **Commands (Prefix & Hybrid Slash)**:
  - **Clan**:
    - `!clan` / `/clan`: Overview card with badge, level, trophies, war log stats, and member counts.
    - `!roster` / `/roster`: Full member roster with sorting (`trophies`, `donations`, `th`, `role`) and role filters (`elder`, `coLeader`, `leader`, `member`).
    - `!top` / `/top`: Top N members ranked by trophies, donations, or Town Hall level.
  - **Player**:
    - `!member` / `/member`: Rich profile card attaching the exact Town Hall level WebP illustration, hero levels, trophies, and donations.
    - `!th` / `/th`: Inspection card showing the Town Hall image for levels 1–19.
    - `!topplayers` / `/topplayers`: Clan leaderboard by war stars or capital contributions.
    - `!trend` / `/trend`: Historical 14-day metric trend for a player.
    - `!compare` / `/compare`: Side-by-side comparison between two clan members.
    - `!cwl` / `/cwl`: Clan War League season status and standings table.
    - `!inactive` / `/inactive`: List of members with 0 donations in the current snapshot cycle.
  - **War**:
    - `!war` / `/war`: Active or most recent war scorecard with stars, destruction %, and time remaining.
    - `!attacks` / `/attacks`: Roster of clan members who have not used their war attacks.
    - `!lineup` / `/lineup`: War map lineup comparison by base position.
    - `!warlog` / `/warlog`: Historical list of past war outcomes.
    - `!warstats` / `/warstats`: Overall clan war performance (win rate, war streak, average stars).
  - **Raid**:
    - `!raid` / `/raid`: Summary of the active or most recent Capital Raid Weekend (medals, attacks, capital gold looted).
    - `!raidmembers` / `/raidmembers`: Detailed breakdown of each member's raid attacks and gold earned.
    - `!raidabsent` / `/raidabsent`: Members who contributed 0 attacks during Raid Weekend.
  - **Admin & Diagnostics**:
    - `/notif list`: List all 14 notification events and their active status.
    - `/notif set <event> <on|off>`: Toggle individual notification events.
    - `/notif channel <event|all> [#channel]`: Route notifications to specific Discord channels.
    - `/notif ping <event|all> [@role]`: Set role mentions for notification events.
    - `/notif quiet [start] [end] [enabled]`: Configure midnight quiet hours.
    - `/notif test <event>`: Send a sample event card.
    - `/notif reset`: Clear anti-spam runtime state to allow re-announcing.
    - `!broadcast` / `/broadcast`: Moderator announcement broadcast embed.
    - `!config` / `/config`: Display current guild configuration and quiet hours.
    - `!freshness` / `/freshness`: Check timestamp and age in hours of the underlying scraper data.

- **Notification Engine (`bot.notifier` & `bot.events`)**:
  - Background asynchronous dispatcher polling data snapshots every 5 minutes.
  - Decoupled guild configuration (`<guild>.json`) and runtime anti-spam state (`<guild>.state.json`).
  - Native integration with 14 event triggers:
    1. `war.preparation`: War opponent matched and preparation day opened.
    2. `war.result`: Final war outcome (Victory / Defeat / Tie).
    3. `war.ending_soon`: War ending in less than 2 hours with attacks pending.
    4. `war.attack_reminder`: Warning for members with remaining attacks.
    5. `war.cleanup`: Post-war attack accountability summary.
    6. `raid.start`: Capital Raid Weekend opened.
    7. `raid.summary`: Raid Weekend concluded with total medals and loot.
    8. `raid.reminder`: Raid Weekend ending warning for unused attacks.
    9. `clan.roster`: Member join / leave detections.
    10. `clan.donation_reset`: Monthly season reset detection.
    11. `clan.donation_weekly`: Weekly donation standings report.
    12. `clan.inactive`: Warning for zero-donation members.
    13. `cwl.round`: CWL round change or war day transition.
    14. `system.stale`: Automated watchdog alerting if scraper data is overdue (>24h).

- **Automated Test Suite**:
  - 49 unit tests covering all cogs, embed builders, configuration store, snapshot reader, event triggers, and the notifier dispatcher (`python3 -m unittest discover tests`).
