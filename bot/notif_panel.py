"""Interactive notification control panel for Discord.

Typing `war.attack_reminder` and a raw channel id is the price of the plain
subcommands. This module removes both: one slash command opens a message with a
dropdown of every notification (grouped, with the current state and a plain
description of when it fires), buttons to switch it on or off, and Discord's own
channel and role pickers instead of asking a human for snowflakes.

Everything here is presentation plus a thin call into ConfigStore. The triggers
and the dispatcher are untouched, so a mis-click can only change config, never
notification behaviour mid-tick.

State lives on the view instance and every callback edits the same message, so
the panel always shows what the config file actually says rather than what the
user last clicked.
"""

import logging

import discord
from discord import ui

from bot.events import (
    GROUP_EMOJI,
    GROUP_LABELS,
    event_help,
    event_keys,
    event_label,
    grouped_keys,
)

log = logging.getLogger("99n.notif_panel")

ALL_VALUE = "__all__"


def event_status(config, key):
    """``(enabled, channel_id, role_id)`` for one event key."""
    spec = (config.get("events") or {}).get(key) or {}
    return bool(spec.get("enabled")), spec.get("channel_id"), spec.get("ping_role_id")


def build_panel_embed(config, selected=None):
    """Status of every notification, grouped, in plain language."""
    embed = discord.Embed(
        title="🔔 Notification settings",
        description=(
            "Pick a notification from the menu, then use the buttons below.\n"
            "**All events** in the menu applies your choice to everything at once."
        ),
        color=0x5865F2,
    )

    for group, keys in grouped_keys():
        lines = []
        for key in keys:
            enabled, channel_id, role_id = event_status(config, key)
            mark = "✅" if enabled else "⛔"
            bits = []
            if channel_id:
                bits.append(f"<#{channel_id}>")
            if role_id:
                bits.append(f"<@&{role_id}>")
            detail = " · ".join(bits) if bits else "no channel yet"
            pointer = "▶ " if key == selected else ""
            lines.append(f"{pointer}{mark} **{event_label(key)}** — {detail}")
        embed.add_field(
            name=f"{GROUP_EMOJI.get(group, '•')} {GROUP_LABELS.get(group, group.title())}",
            value="\n".join(lines),
            inline=False,
        )

    selected_text = event_label(selected) if selected else "nothing yet"
    embed.set_footer(text=f"Selected: {selected_text} · changes apply immediately")
    return embed


def event_options(config, include_all=True):
    """Dropdown entries: every event, grouped by order, states spelled out."""
    options = []
    for group, keys in grouped_keys():
        for key in keys:
            enabled, _, _ = event_status(config, key)
            options.append(
                discord.SelectOption(
                    label=("✅ " if enabled else "⛔ ") + event_label(key),
                    value=key,
                    emoji=GROUP_EMOJI.get(group, None),
                    description=event_help(key) or None,
                )
            )
    if include_all:
        options.append(
            discord.SelectOption(
                label="All notifications",
                value=ALL_VALUE,
                emoji="🔁",
                description="Apply the next action to every notification",
            )
        )
    # Discord caps a select menu at 25 options; the registry is far below that.
    return options[:25]


class NotifPanel(ui.View):
    """Live control panel bound to one guild's config."""

    def __init__(self, config_store, guild_id, author_id, timeout=600):
        super().__init__(timeout=timeout)
        self.config_store = config_store
        self.guild_id = guild_id
        self.author_id = author_id
        self.selected = None

        config = self.config_store.get(self.guild_id)
        self.event_select.options = event_options(config)

        self._sync_actions()

    # -- rows ---------------------------------------------------------------

    @ui.select(placeholder="Choose a notification…", row=0)
    async def event_select(self, interaction: discord.Interaction, select: ui.Select):
        self.selected = select.values[0]
        self._sync_actions()
        await self._refresh(interaction)

    @ui.button(label="Turn on", style=discord.ButtonStyle.success, row=1)
    async def on_button(self, interaction: discord.Interaction, button: ui.Button):
        self._apply_enabled(True)
        await self._refresh(interaction, f"Enabled **{self._scope_text()}**.")

    @ui.button(label="Turn off", style=discord.ButtonStyle.danger, row=1)
    async def off_button(self, interaction: discord.Interaction, button: ui.Button):
        self._apply_enabled(False)
        await self._refresh(interaction, f"Disabled **{self._scope_text()}**.")

    @ui.button(label="Send a sample", style=discord.ButtonStyle.primary, row=1)
    async def test_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.selected in (None, ALL_VALUE):
            await interaction.response.send_message(
                "Pick one notification first, then press **Send a sample**.",
                ephemeral=True,
            )
            return
        from bot.notifier import build_context, StateStore
        from bot.events import NOTIFY_EVENTS
        from bot import bot_config

        states = StateStore(str(bot_config.CONFIG_DIR))
        reader = bot_config.build_reader()
        ctx_data = build_context(reader, states.get(self.guild_id))
        await interaction.response.defer(ephemeral=True)

        embeds = NOTIFY_EVENTS[self.selected](ctx_data, {})
        if not embeds:
            from bot.cogs.admin import _preview

            embeds = _preview(self.selected, ctx_data)
        if not embeds:
            await interaction.followup.send(
                f"Nothing to show for **{event_label(self.selected)}** right now.",
                ephemeral=True,
            )
            return
        # Samples never touch the real notification channel.
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.select(
        cls=ui.ChannelSelect,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        placeholder="Send to which channel…",
        row=2,
    )
    async def channel_select(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        if self.selected is None:
            await interaction.response.send_message(
                "Pick a notification from the menu first (or **All notifications**).",
                ephemeral=True,
            )
            return
        target = select.values[0]
        self._apply_channel(target.id)
        await self._refresh(
            interaction, f"**{self._scope_text()}** now goes to <#{target.id}>."
        )

    @ui.select(cls=ui.RoleSelect, placeholder="…and mention which role (optional)", row=3)
    async def role_select(self, interaction: discord.Interaction, select: ui.RoleSelect):
        if self.selected is None:
            await interaction.response.send_message(
                "Pick a notification from the menu first (or **All notifications**).",
                ephemeral=True,
            )
            return
        target = select.values[0]
        self._apply_role(target.id)
        await self._refresh(
            interaction, f"**{self._scope_text()}** will mention {target.mention}."
        )

    @ui.button(label="Quiet hours", style=discord.ButtonStyle.secondary, row=4)
    async def quiet_button(self, interaction: discord.Interaction, button: ui.Button):
        config = self.config_store.get(self.guild_id)
        current = config["quiet_hours"]
        self.config_store.set_quiet_hours(
            self.guild_id, not current.get("enabled"),
            start=current.get("start"), end=current.get("end"),
        )
        now = self.config_store.get(self.guild_id)["quiet_hours"]
        state = "on" if now["enabled"] else "off"
        await self._refresh(
            interaction,
            f"Quiet hours **{state}** ({now['start']}–{now['end']}). "
            "Change the times with `/notif quiet`.",
        )

    @ui.button(label="Forget sent state", style=discord.ButtonStyle.secondary, row=4)
    async def reset_button(self, interaction: discord.Interaction, button: ui.Button):
        from bot.notifier import StateStore
        from bot import bot_config

        StateStore(str(bot_config.CONFIG_DIR)).clear(self.guild_id)
        await self._refresh(interaction, "Cleared what was already sent; events can fire again.")

    @ui.button(label="Close", style=discord.ButtonStyle.secondary, row=4)
    async def close_button(self, interaction: discord.Interaction, button: ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="Panel closed. Reopen it any time with `/notif panel`.",
            embed=None,
            view=None,
        )

    # -- helpers ------------------------------------------------------------

    def _scope_keys(self):
        """Which event keys the next action applies to."""
        if self.selected == ALL_VALUE:
            return list(event_keys())
        if self.selected:
            return [self.selected]
        return []

    def _scope_text(self):
        if self.selected == ALL_VALUE:
            return "all notifications"
        if self.selected:
            return event_label(self.selected)
        return "your selection"

    def _sync_actions(self):
        """Enable the action buttons only once something is selected.

        A disabled button explains itself; an error message after the click
        does not.
        """
        ready = self.selected is not None
        for item in (self.on_button, self.off_button):
            item.disabled = not ready
        # The pickers need a target the same way the buttons do; leaving them
        # clickable only produces an error after the choice is already made.
        for item in (self.channel_select, self.role_select):
            item.disabled = not ready
        self.test_button.disabled = self.selected in (None, ALL_VALUE)

    def _apply_enabled(self, value):
        for key in self._scope_keys():
            self.config_store.set(self.guild_id, f"events.{key}.enabled", value)

    def _apply_channel(self, channel_id):
        self.config_store.set_channel(self.guild_id, self._scope_key(), channel_id)

    def _apply_role(self, role_id):
        self.config_store.set_role(self.guild_id, self._scope_key(), role_id)

    def _scope_key(self):
        """ConfigStore spells the wildcard ``all``; the menu spells it ``__all__``."""
        if self.selected == ALL_VALUE:
            return "all"
        return self.selected

    async def _refresh(self, interaction, note=None):
        """Re-render from the config file so the panel never lies about it."""
        config = self.config_store.get(self.guild_id)
        self.event_select.options = event_options(config)
        self._sync_actions()
        embed = build_panel_embed(config, selected=self.selected)
        if note:
            embed.add_field(name="Last change", value=note, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Open your own panel with `/notif panel`.", ephemeral=True
            )
            return False
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "You need **Manage Server** to change notifications.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        log.debug("notification panel timed out for guild %s", self.guild_id)
