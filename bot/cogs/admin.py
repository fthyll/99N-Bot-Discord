"""Admin commands: configure notifications, broadcast, show config."""

import asyncio

import discord
from discord.ext import commands

from bot import bot_config
from bot.config_store import ConfigStore
from bot.events import (
    GROUP_LABELS,
    event_help,
    event_keys,
    event_label,
    grouped_keys,
)
from bot.formatting import truncate
from bot.notifier import StateStore, build_context, next_state


def build_notif_table(config):
    """Rows describing every event and its current state."""
    rows = []
    for key in event_keys():
        spec = config["events"][key]
        group = GROUP_LABELS.get(key.split(".")[0], key.split(".")[0])
        rows.append({
            "key": key,
            "group": group,
            "enabled": bool(spec.get("enabled")),
            "channel_id": spec.get("channel_id"),
            "ping_role_id": spec.get("ping_role_id"),
        })
    return rows


def build_config_summary(config):
    qh = config.get("quiet_hours", {})
    lines = [
        f"**Timezone**: {config.get('timezone', 'Asia/Jakarta')}",
        f"**Quiet hours**: {'on' if qh.get('enabled') else 'off'} "
        f"({qh.get('start', '23:00')}–{qh.get('end', '07:00')})",
    ]
    enabled = [k for k in event_keys() if config["events"][k].get("enabled")]
    lines.append(f"**Enabled events**: {len(enabled)}/{len(event_keys())}")
    return "\n".join(lines)


# Presets apply a common setup in one command. A human setting up the bot
# usually wants "all war pings here, all raid pings there" or "turn everything
# off except war result", not 14 separate /notif commands.
PRESETS = {
    "all": {
        "label": "All notifications",
        "description": "Turn on every notification the bot supports",
        "keys": list(event_keys()),
    },
    "essential": {
        "label": "Essential only (low noise)",
        "description": "War matches & results, raid opens & finishes, roster changes",
        "keys": ["war.preparation", "war.result", "raid.start", "raid.summary", "clan.roster"],
    },
    "war-only": {
        "label": "War room only",
        "description": "Match, result, ending soon, and attack reminders",
        "keys": [k for k in event_keys() if k.startswith("war.")],
    },
    "raid-only": {
        "label": "Raid weekend only",
        "description": "Raid start, summary, and reminders",
        "keys": [k for k in event_keys() if k.startswith("raid.")],
    },
}


async def event_autocomplete(
    interaction: discord.Interaction, current: str, include_all: bool = True
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for the ``event`` parameter across all /notif subcommands.

    Matches either the dotted key or any word in the human label, so a user
    typing 'reminder' finds both war.attack_reminder and raid.reminder
    without knowing the exact dot-syntax.

    ``include_all`` is False where the wildcard would be meaningless, e.g.
    ``/notif test`` which sends exactly one card.
    """
    needle = (current or "").strip().lower()
    choices = []
    if include_all and (not needle or needle in "all"):
        choices.append(discord.app_commands.Choice(name="🔁 All notifications (all)", value="all"))
    for key in event_keys():
        haystack = f"{key} {event_label(key)}".lower()
        if not needle or needle in haystack:
            name = f"{event_label(key)} ({key})"
            if len(name) > 100:
                name = name[:97] + "..."
            choices.append(discord.app_commands.Choice(name=name, value=key))
            if len(choices) >= 25:
                break
    return choices


class AdminCog(commands.Cog, name="admin"):
    """Slash-only: these commands change server-side configuration."""

    def __init__(self, bot):
        self.bot = bot
        self.reader = bot_config.build_reader()
        self.config = ConfigStore(str(bot_config.CONFIG_DIR))
        self.states = StateStore(str(bot_config.CONFIG_DIR))

    # -- /notif -----------------------------------------------------------
    @commands.hybrid_group(name="notif", description="Configure notification events")
    async def notif(self, ctx):
        """Configure notification events."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `/notif panel` for an interactive menu, or `/notif list` to see every event.")

    @notif.command(name="panel", description="Open an interactive notification control panel")
    @commands.has_permissions(manage_guild=True)
    async def notif_panel_cmd(self, ctx):
        """Interactive control panel with menus and buttons."""
        from bot.notif_panel import NotifPanel, build_panel_embed

        config = self.config.get(ctx.guild.id)
        embed = build_panel_embed(config)
        view = NotifPanel(self.config, ctx.guild.id, ctx.author.id)
        await ctx.send(embed=embed, view=view)

    @notif.command(name="preset", description="Apply a pre-configured notification profile")
    @commands.has_permissions(manage_guild=True)
    async def notif_preset_cmd(
        self,
        ctx,
        profile: str,
        channel: discord.TextChannel = None,
    ):
        """Apply a group of notifications in one go (essential, war-only, raid-only, all)."""
        target = profile.strip().lower()
        if target not in PRESETS:
            valid = ", ".join(f"`{k}`" for k in PRESETS)
            await ctx.send(f"❌ Unknown preset `{profile}`. Choose one of: {valid}.")
            return
        spec = PRESETS[target]
        target_channel = channel or ctx.channel

        # Turn on the chosen set, turn off everything else.
        for key in event_keys():
            enabled = key in spec["keys"]
            self.config.set(ctx.guild.id, f"events.{key}.enabled", enabled)
            if enabled:
                self.config.set_channel(ctx.guild.id, key, target_channel.id)

        embed = discord.Embed(
            title=f"✅ Applied preset: {spec['label']}",
            description=(
                f"{spec['description']}\n"
                f"Enabled **{len(spec['keys'])}** notifications → <#{target_channel.id}>."
            ),
            color=0x57F287,
        )
        await ctx.send(embed=embed)

    @notif_preset_cmd.autocomplete("profile")
    async def _notif_preset_autocomplete(self, interaction, current):
        needle = (current or "").strip().lower()
        return [
            discord.app_commands.Choice(
                name=f"{info['label']} — {info['description']}"[:100],
                value=key,
            )
            for key, info in PRESETS.items()
            if not needle or needle in key or needle in info["label"].lower()
        ][:25]

    @notif.command(name="list", description="List every event and its state")
    @commands.has_permissions(manage_guild=True)
    async def notif_list(self, ctx):
        config = self.config.get(ctx.guild.id)
        embed = discord.Embed(
            title="🔔 Notification events",
            description="Use `/notif panel` to edit these with a visual menu.",
            color=0x5865F2,
        )
        for group, keys in grouped_keys():
            lines = []
            for key in keys:
                spec = config["events"][key]
                mark = "✅" if spec.get("enabled") else "⛔"
                channel = f"<#{spec['channel_id']}>" if spec.get("channel_id") else "no channel"
                role = f"<@&{spec['ping_role_id']}>" if spec.get("ping_role_id") else ""
                route = f" → {channel}" + (f" ({role})" if role else "")
                lines.append(f"{mark} **{event_label(key)}** (`{key}`){route}")
            embed.add_field(
                name=GROUP_LABELS.get(group, group.title()),
                value="\n".join(lines),
                inline=False,
            )
        await ctx.send(embed=embed)

    @notif.command(name="set", description="Enable or disable one event")
    @commands.has_permissions(manage_guild=True)
    async def notif_set(self, ctx, event: str, state: str):
        if event != "all" and event not in event_keys():
            await ctx.send(f"❌ Unknown event `{event}`. Use `/notif list` or type to autocomplete.")
            return
        value = str(state).lower() in ("on", "true", "yes", "1", "enable", "enabled")
        keys = list(event_keys()) if event == "all" else [event]
        for key in keys:
            self.config.set(ctx.guild.id, f"events.{key}.enabled", value)
        action = "Enabled" if value else "Disabled"
        target_name = "all notifications" if event == "all" else f"`{event}` ({event_label(event)})"
        await ctx.send(f"{'✅' if value else '⛔'} {action} {target_name}.")

    @notif_set.autocomplete("event")
    async def _notif_set_autocomplete(self, interaction, current):
        return await event_autocomplete(interaction, current)

    @notif_set.autocomplete("state")
    async def _notif_state_autocomplete(self, interaction, current):
        return [
            discord.app_commands.Choice(name="✅ On (enabled)", value="on"),
            discord.app_commands.Choice(name="⛔ Off (disabled)", value="off"),
        ]

    @notif.command(name="channel", description="Route an event to a channel")
    @commands.has_permissions(manage_guild=True)
    async def notif_channel(self, ctx, event: str, channel: discord.TextChannel = None):
        target = channel or ctx.channel
        if event != "all" and event not in event_keys():
            await ctx.send(f"❌ Unknown event `{event}`. Use `/notif list` or type to autocomplete.")
            return
        self.config.set_channel(ctx.guild.id, event, target.id)
        target_name = "All notifications" if event == "all" else f"`{event}`"
        await ctx.send(f"📨 {target_name} now go to <#{target.id}>.")

    @notif_channel.autocomplete("event")
    async def _notif_channel_autocomplete(self, interaction, current):
        return await event_autocomplete(interaction, current)

    @notif.command(name="ping", description="Mention a role when an event fires")
    @commands.has_permissions(manage_guild=True)
    async def notif_ping(self, ctx, event: str, role: discord.Role = None):
        if event != "all" and event not in event_keys():
            await ctx.send(f"❌ Unknown event `{event}`. Use `/notif list` or type to autocomplete.")
            return
        role_id = role.id if role else None
        self.config.set_role(ctx.guild.id, event, role_id)
        target_name = "All notifications" if event == "all" else f"`{event}`"
        await ctx.send(
            f"🔔 {target_name} will mention {role.mention if role else 'nobody'}."
        )

    @notif_ping.autocomplete("event")
    async def _notif_ping_autocomplete(self, interaction, current):
        return await event_autocomplete(interaction, current)

    @notif.command(name="quiet", description="Set quiet hours")
    @commands.has_permissions(manage_guild=True)
    async def notif_quiet(self, ctx, start: str = None, end: str = None, enabled: bool = True):
        self.config.set_quiet_hours(ctx.guild.id, enabled, start=start, end=end)
        config = self.config.get(ctx.guild.id)
        qh = config["quiet_hours"]
        await ctx.send(
            f"🌙 Quiet hours {'on' if qh['enabled'] else 'off'}: "
            f"{qh['start']}–{qh['end']} ({config.get('timezone', 'Asia/Jakarta')})."
        )

    @notif.command(name="test", description="Send a sample notification")
    @commands.has_permissions(manage_guild=True)
    async def notif_test(self, ctx, event: str):
        if event not in event_keys():
            await ctx.send(f"❌ Unknown event `{event}`. Use `/notif list` or type to autocomplete.")
            return
        from bot.events import NOTIFY_EVENTS
        from bot.offload import live_context

        await ctx.defer()
        state = self.states.get(ctx.guild.id)
        ctx_data = await live_context(self.reader, state, event)
        # Force the trigger to produce something by clearing its marker.
        embeds = NOTIFY_EVENTS[event](ctx_data, {})
        if not embeds:
            # Fall back to a preview built from the current snapshot.
            embeds = _preview(event, ctx_data)
        if not embeds:
            await ctx.send(f"Nothing to preview for `{event}` right now.")
            return
        for embed in embeds:
            await ctx.send(embed=embed)

    @notif_test.autocomplete("event")
    async def _notif_test_autocomplete(self, interaction, current):
        return await event_autocomplete(interaction, current, include_all=False)

    @notif.command(name="reset", description="Forget which notifications were already sent")
    @commands.has_permissions(manage_guild=True)
    async def notif_reset(self, ctx):
        self.states.clear(ctx.guild.id)
        await ctx.send("🧹 Notification state cleared; events may fire once again.")

    # -- /broadcast & /config ---------------------------------------------
    @commands.hybrid_command(name="broadcast", description="Send a one-off message")
    @commands.has_permissions(manage_guild=True)
    async def broadcast(self, ctx, text: str, channel: discord.TextChannel = None):
        target = channel or ctx.channel
        embed = discord.Embed(
            title="📢 Announcement",
            description=text,
            color=0xF5B942,
        )
        embed.set_footer(text="99N War Room · broadcast")
        await target.send(embed=embed)

    @commands.hybrid_command(name="config", description="Show the notification config")
    @commands.has_permissions(manage_guild=True)
    async def config_show(self, ctx):
        config = self.config.get(ctx.guild.id)
        embed = discord.Embed(title="⚙️ Notification config", color=0x5865F2)
        embed.description = build_config_summary(config)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="freshness", description="Where the bot's data comes from and how old it is")
    async def freshness(self, ctx):
        status = self.reader.status() if hasattr(self.reader, "status") else None
        embed = discord.Embed(title="🕒 Data freshness", color=0x95A5A6)
        if status and status.get("mode") == "live":
            # Live mode: a "snapshot age" would be meaningless — the data is
            # fetched from Supercell, not read from a file.
            lines = [
                "**Source**: Clash of Clans API (live)",
                f"**Cache warm**: {'yes' if status.get('ready') else 'warming up'}",
                f"**Last refresh**: {status.get('last_refresh') or 'pending'}",
                f"**Refresh every**: {status.get('interval_seconds')}s",
            ]
            errors = status.get("errors") or {}
            if errors:
                lines.append("**Unavailable**: " + ", ".join(sorted(errors)))
            embed.description = "\n".join(lines)
            embed.color = 0x57F287 if not errors else 0xF5B942
        else:
            stamp = self.reader.freshest_stamp()
            age = self.reader.age_hours(stamp)
            embed.description = (
                f"**Source**: committed snapshots\n"
                f"**Newest snapshot**: {stamp or 'unknown'}\n"
                f"**Age**: {age:.1f}h" if age is not None
                else f"**Source**: committed snapshots\n**Age**: unknown"
            )
            if age is not None and age > bot_config.MAX_SNAPSHOT_AGE_HOURS:
                embed.color = 0xED4245
        await ctx.send(embed=embed)


    @commands.hybrid_command(name="logs", description="Tail the bot log file (admin)")
    @commands.has_permissions(manage_guild=True)
    async def logs(self, ctx, lines: int = 30, level: str = None):
        """Show the tail of ``logs/bot.log`` without opening a terminal.

        ``level`` filters case-insensitively (e.g. ``error`` or ``warning``);
        omission shows every line. Runs in a thread so a large file cannot
        stall the event loop.
        """
        from bot.logging_setup import log_dir

        lines = max(1, min(int(lines or 30), 200))
        path = log_dir() / "bot.log"
        if not path.exists():
            await ctx.send(f"No log file yet at `{path}`. File logging may be disabled.")
            return

        def tail():
            # ponytail: whole-file read. A rotated log is capped at 5 MB, so
            # this is bounded by construction; switch to a reverse seek if the
            # rotation limit ever grows past tens of MB.
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                return fh.readlines()

        try:
            # The running loop, not ctx.bot.loop: discord.Client.loop raises
            # AttributeError when read outside a running loop.
            loop = asyncio.get_running_loop()
            all_lines = await loop.run_in_executor(None, tail)
        except OSError as exc:
            await ctx.send(f"Could not read the log: `{exc}`")
            return

        if level:
            wanted = level.strip().upper()
            all_lines = [l for l in all_lines if f" {wanted} " in l]

        shown = all_lines[-lines:]
        embed = discord.Embed(
            title=f"📜 Last {len(shown)} log line(s)" + (f" · {level.upper()}" if level else ""),
            description=f"```\n{truncate(''.join(shown).strip(), 3800) or '(empty)'}\n```",
            color=0x5865F2,
        )
        embed.set_footer(text=str(path))
        await ctx.send(embed=embed)


def _preview(event, ctx_data):
    """Build a sample payload for /notif test when no transition is pending."""
    from bot.embeds import dict_to_embed

    if event.startswith("war.") and ctx_data.get("war"):
        from bot.cogs.war import build_war_embed
        return [build_war_embed(ctx_data["war"])]
    if event.startswith("raid.") and ctx_data.get("raid"):
        from bot.cogs.raid import build_raid_embed
        return [build_raid_embed(ctx_data["raid"])]
    if event.startswith("clan.") and ctx_data.get("clan"):
        from bot.cogs.clan import build_clan_embed
        return [build_clan_embed(ctx_data["clan"])]
    if event == "cwl.round":
        cwl = (ctx_data.get("meta") or {}).get("cwl") or {}
        return [discord.Embed(
            title="🏆 CWL update",
            description=f"State: **{cwl.get('state', 'unknown')}**",
            color=0xF5B942,
        )]
    if event == "system.stale":
        return [discord.Embed(
            title="⚠️ 99N scrapers look stalled",
            description="The dashboard is serving stale data.",
            color=0xED4245,
        )]
    return []


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
