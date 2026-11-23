"""Verify the slash command surface: autocomplete bindings and help text.

Autocomplete attached to the wrong parameter name, or a subcommand whose
description is missing, fails silently — Discord just shows no suggestions and
plain command text. Nothing about it appears in a unit test that calls the
callback directly, so this walks the built CommandTree instead.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord
from discord.ext import commands

from bot import bot_config
from bot.cogs.admin import PRESETS
from bot.events import event_keys, event_label
from bot.notif_panel import ALL_VALUE, NotifPanel
from bot.config_store import ConfigStore
import tempfile

failures = []


def check(name, condition, detail=None):
    print(f"  {'ok  ' if condition else 'FAIL'} {name}" + ("" if condition else f"  {detail}"))
    if not condition:
        failures.append(name)


async def main():
    bot = commands.Bot(command_prefix="", intents=discord.Intents.none())
    await bot.load_extension("bot.cogs.admin")

    # No gateway or sync needed: walk the locally built tree.
    cmds = {c.qualified_name: c for c in bot.tree.walk_commands()}

    print("registration")
    for name in ("notif", "notif panel", "notif preset", "notif set",
                 "notif channel", "notif ping", "notif list", "notif test"):
        check(f"/{name} exists", name in cmds, sorted(cmds))

    print("descriptions")
    for name, cmd in cmds.items():
        if name.startswith("notif"):
            check(f"/{name} has a description",
                  bool(cmd.description) and cmd.description != "No description",
                  repr(cmd.description))

    print("autocomplete bindings")
    # Parameter.autocomplete is only a bool; the callable lives on the
    # underlying _params entry, which is what _invoke_autocomplete calls.
    def callback_for(cmd_name, param):
        """Return a zero-arg-then-(interaction, current) callable.

        The stored callback is the raw function including its ``self``
        parameter when it lives on a cog, so bind the cog here the same way
        discord.py does before invoking it.
        """
        cmd = cmds[cmd_name]
        raw = getattr(cmd, "_params", {}).get(param)
        cb = getattr(raw, "autocomplete", None)
        if cb is None:
            return None
        binding = getattr(cmd, "binding", None)
        if getattr(cb, "pass_command_binding", False) and binding is not None:
            return lambda interaction, current: cb(binding, interaction, current)
        return cb

    def bound(cmd_name, param):
        return callable(callback_for(cmd_name, param))

    check("/notif set autocompletes event", bound("notif set", "event"))
    check("/notif set autocompletes state", bound("notif set", "state"))
    check("/notif channel autocompletes event", bound("notif channel", "event"))
    check("/notif ping autocompletes event", bound("notif ping", "event"))
    check("/notif preset autocompletes profile", bound("notif preset", "profile"))
    check("/notif test autocompletes event", bound("notif test", "event"))

    print("autocomplete output")
    cb = callback_for("notif set", "event")
    choices = await cb(None, "")
    values = [c.value for c in choices]
    check("wildcard offered for /notif set", "all" in values)
    check("all events offered", set(event_keys()) <= set(values), sorted(set(event_keys()) - set(values)))
    check("choices fit Discord's 25 cap", len(choices) <= 25, str(len(choices)))

    cb_state = callback_for("notif set", "state")
    states = [c.value for c in await cb_state(None, "")]
    check("state autocomplete offers on/off", states == ["on", "off"], states)

    cb_test = callback_for("notif test", "event")
    test_values = [c.value for c in await cb_test(None, "")]
    check("/notif test withholds the wildcard", "all" not in test_values)

    cb_preset = callback_for("notif preset", "profile")
    preset_values = [c.value for c in await cb_preset(None, "")]
    check("every preset is autocompleted", set(PRESETS) <= set(preset_values), preset_values)

    print("choices are non-empty and labelled")
    for choice in await cb(None, ""):
        check(f"choice {choice.value!r} has a name", bool(choice.name))

    print("panel command is wired to a view")
    panel = cmds["notif panel"]
    check("panel is a slash subcommand", panel.parent is not None)
    with tempfile.TemporaryDirectory() as d:
        view = NotifPanel(ConfigStore(root=d), 1, 9)
        check("panel view instantiates", len(view.children) == 9, str(len(view.children)))

    await bot.close()


asyncio.run(main())
print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("command surface probe: all checks passed")
