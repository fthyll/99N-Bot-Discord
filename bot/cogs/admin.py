"""Admin commands: configure notifications, broadcast, show config."""

import asyncio

import discord
from discord.ext import commands

from bot import bot_config
from bot.config_store import ConfigStore
from bot.events import GROUP_LABELS, event_keys
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
            await ctx.send("Use `/notif list` to see every event.")

    @notif.command(name="list", description="List every event and its state")
    @commands.has_permissions(manage_guild=True)
    async def notif_list(self, ctx):
        config = self.config.get(ctx.guild.id)
        lines = []
        for row in build_notif_table(config):
            mark = "✅" if row["enabled"] else "❌"
            channel = row["channel_id"] or "—"
            role = row["ping_role_id"] or "—"
            lines.append(f"{mark} `{row['key']}` · channel {channel} · role {role}")
        embed = discord.Embed(title="🔔 Notification events", color=0x5865F2)
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @notif.command(name="set", description="Enable or disable one event")
    @commands.has_permissions(manage_guild=True)
    async def notif_set(self, ctx, event: str, state: str):
        if event not in event_keys():
            await ctx.send(f"❌ Unknown event `{event}`. Use `/notif list`.")
            return
        value = str(state).lower() in ("on", "true", "yes", "1", "enable", "enabled")
        self.config.set(ctx.guild.id, f"events.{event}.enabled", value)
        await ctx.send(f"{'✅ Enabled' if value else '❌ Disabled'} `{event}`.")

    @notif.command(name="channel", description="Route an event to a channel")
    @commands.has_permissions(manage_guild=True)
    async def notif_channel(self, ctx, event: str, channel: discord.TextChannel = None):
        target = channel or ctx.channel
        if event != "all" and event not in event_keys():
            await ctx.send(f"❌ Unknown event `{event}`. Use `/notif list`.")
            return
        self.config.set_channel(ctx.guild.id, event, target.id)
        await ctx.send(f"📨 `{event}` notifications now go to <#{target.id}>.")

    @notif.command(name="ping", description="Mention a role when an event fires")
    @commands.has_permissions(manage_guild=True)
    async def notif_ping(self, ctx, event: str, role: discord.Role = None):
        if event != "all" and event not in event_keys():
            await ctx.send(f"❌ Unknown event `{event}`. Use `/notif list`.")
            return
        role_id = role.id if role else None
        self.config.set_role(ctx.guild.id, event, role_id)
        await ctx.send(
            f"🔔 `{event}` will mention {role.mention if role else 'nobody'}."
        )

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
            await ctx.send(f"❌ Unknown event `{event}`. Use `/notif list`.")
            return
        from bot.events import NOTIFY_EVENTS

        state = self.states.get(ctx.guild.id)
        ctx_data = build_context(self.reader, state)
        # Force the trigger to produce something by clearing its marker.
        embeds = NOTIFY_EVENTS[event](ctx_data, {})
        if not embeds:
            # Fall back to a preview built from the current snapshot.
            from bot.events import NOTIFY_EVENTS as _events  # noqa: F401
            embeds = _preview(event, ctx_data)
        if not embeds:
            await ctx.send(f"Nothing to preview for `{event}` right now.")
            return
        for embed in embeds:
            await ctx.send(embed=embed)

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
