"""Ship the bot's log lines to a Discord channel.

The rotating file is for the operator; a log channel is for the guild, where
"the war notification never fired" is a question the officers ask. Opt-in via
``LOG_CHANNEL_ID`` — a bot that posts its own logs uninvited is noise.

Two rules this module exists to honour:

* **Never block the event loop.** ``logging`` calls come from many threads,
  including the `WarmCache` daemon, so :meth:`DiscordLogHandler.emit` only
  appends to a thread-safe deque and asks the loop to drain it. The HTTP send
  happens in the bot's own task. Note that ``bot.loop`` cannot be used to find
  that loop: ``discord.Client.loop`` raises ``AttributeError`` as soon as it is
  read outside a running loop, so :meth:`attach` must be called from async code
  and captures the loop with ``asyncio.get_running_loop()``.
* **Never take the process down over a logger.** A Discord outage while
  logging drops lines; it must not raise into whatever was logging.

A plain :class:`collections.deque` carries the records rather than an
``asyncio.Queue`` because a queue binds to an event loop lazily — a handler
attached before the loop is running would bind to the wrong one and every
drain would raise *"attached to a different loop"*.
"""

import asyncio
import collections
import logging

# Cap the buffer so a burst cannot grow without bound; the file log still holds
# every line, so dropping from the channel costs nothing permanent.
MAX_QUEUE = 200
# Batch size: one message per log line would rate-limit instantly during a
# dispatcher tick that fires several notifications at once.
MAX_BATCH = 10
# Discord's hard message limit is 2000; stay well under it.
MAX_CHARS = 1800


class DiscordLogHandler(logging.Handler):
    """A logging handler that posts queued records to a Discord channel.

    Inert until :meth:`attach` binds a running bot, so importing this module
    never needs a live client.
    """

    def __init__(self, channel_id, level=logging.INFO):
        super().__init__(level=level)
        self.channel_id = int(channel_id)
        self.bot = None
        self.loop = None
        # deque.append/popleft are atomic, so this is safe from any thread.
        self._buffer = collections.deque(maxlen=MAX_QUEUE)
        self._pending = False
        self._dropped = 0

    def attach(self, bot, loop=None):
        """Bind to a running bot. Call this from async code.

        ``discord.Client.loop`` raises when read outside a running loop, so the
        loop is taken from ``asyncio.get_running_loop()`` unless one is passed.
        """
        self.bot = bot
        self.loop = loop or asyncio.get_running_loop()

    def emit(self, record):
        if self.loop is None:
            return
        try:
            text = self.format(record)
        except Exception:  # a broken formatter must not kill the caller
            return
        if len(self._buffer) == MAX_QUEUE:
            self._dropped += 1
        self._buffer.append(text)
        try:
            self.loop.call_soon_threadsafe(self._kick)
        except (RuntimeError, AttributeError):
            # RuntimeError: loop closed during shutdown. AttributeError: a bot
            # stub without a usable loop. The file handler already has the line.
            pass

    def _kick(self):
        """Runs on the bot's loop: start a drain unless one is already going."""
        if self._pending or not self._buffer:
            return
        self._pending = True
        self.loop.create_task(self._flush())

    async def _flush(self):
        try:
            while self._buffer:
                batch = []
                while self._buffer and len(batch) < MAX_BATCH:
                    batch.append(self._buffer.popleft())
                await self._post("\n".join(batch))
            if self._dropped:
                dropped, self._dropped = self._dropped, 0
                await self._post(f"… {dropped} log line(s) dropped (channel flooded)")
        except asyncio.CancelledError:
            raise
        except Exception:
            # Logging must never crash the loop it reports on.
            pass
        finally:
            self._pending = False
            # A line logged while we were sending needs another pass.
            if self._buffer:
                self._kick()

    async def _post(self, text):
        channel = self.bot.get_channel(self.channel_id) if self.bot else None
        if channel is None:
            return
        try:
            await channel.send(f"```\n{text[:MAX_CHARS]}\n```")
        except Exception:
            pass


def attach_discord_log(channel_id, bot, level=logging.INFO, loop=None):
    """Wire the channel handler onto the root logger and return it.

    Must be called from async code (see :meth:`DiscordLogHandler.attach`).
    Returns None when no channel is configured, so the caller can call this
    unconditionally.
    """
    if not channel_id:
        return None
    handler = DiscordLogHandler(channel_id, level=level)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"))
    handler.attach(bot, loop=loop)
    logging.getLogger().addHandler(handler)
    return handler
