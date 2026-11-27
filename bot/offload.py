"""Keeps the CoC API cache warm off the Discord event loop.

The problem, concretely: every cog holds a reader and calls it synchronously
from an async command, and ``players()`` costs one request per member. Calling
that inline would stall the event loop for ~50 round trips, heartbeats
included, until Discord drops the session.

Rather than make 22 call sites async (and every cache read an ``await``), the
client stays synchronous and one background thread refreshes it on a timer.
Cogs read whatever the last refresh produced, so they never block on a socket.

``WarmCache`` forwards every attribute to the client, which already implements
the whole ``SnapshotReader`` interface — so ``build_reader()`` can return a
warmer instead of a client and not one cog changes.

Trade-off, stated plainly: a command may serve data up to one refresh interval
old. That is the freshness snapshot mode had anyway, and it costs one daemon
thread with no new dependency.
"""

import asyncio
import threading

from bot.coc_api import CocApiError, CocClient

#: Refreshing ``trends()`` is local file I/O and ``freshest_stamp()`` is a
#: clock read; neither touches the network, so neither needs warming.
WARMED = ("clan", "war", "raid", "warlog", "players", "meta")


class WarmCache:
    """A ``CocClient`` whose cache a background thread keeps fresh.

    Presents the client's own interface: every attribute lookup that is not
    defined here goes to the client, so cogs cannot tell the difference.
    """

    def __init__(self, client, interval_seconds=600):
        if not isinstance(client, CocClient):
            raise TypeError("WarmCache wraps a CocClient")
        self.client = client
        self.interval = max(30, int(interval_seconds))
        self._stop = threading.Event()
        # Set when a command asks for fresh data; the warm thread checks it
        # instead of waiting out the whole interval.
        self._soon = threading.Event()
        self._thread = None
        self._ready = threading.Event()
        self.last_error = None
        self.last_refresh = None

    # -- passthrough -------------------------------------------------------
    def __getattr__(self, name):
        # Only reached when normal lookup fails, so no infinite recursion:
        # client/warm state live in __dict__.
        return getattr(self.client, name)

    # -- thread lifecycle --------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="coc-warm-cache", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.is_set():
            # Clear BEFORE refreshing: a nudge landing mid-refresh survives
            # and schedules the next pass. Clearing after would swallow it.
            self._soon.clear()
            self.refresh_once()
            # Wait in short slices so a refresh_soon() nudge is honoured
            # within seconds while _stop stays responsive too.
            waited = 0.0
            while waited < self.interval and not self._stop.is_set() and not self._soon.is_set():
                self._soon.wait(0.5)
                waited += 0.5

    def refresh_soon(self):
        """Ask for a refresh ahead of schedule (e.g. after a slash command).

        Coalescing by design: ten commands in a row set the flag ten times and
        the warm thread still refreshes once. Returns immediately; the caller
        must not block the event loop on a refresh.
        """
        self._soon.set()

    def refresh_once(self):
        """One full pass over every warmed endpoint.

        Each endpoint is refreshed independently: a private war log (403) is a
        permanent condition for some clans and must not stop members or raids
        from being warmed.

        The client swallows API failures and serves the committed snapshot
        instead, recording why in ``client.last_errors`` — so that mapping, not
        the exception, is where a dead token shows up.

        Every read passes ``force=True``: a warm pass that serves the previous
        pass's TTL cache is a no-op, and the point of warming (or of a
        refresh_soon nudge) is to refill the cache with data newer than the
        last pass.
        """
        errors = {}
        try:
            self.client.clear_errors()
        except AttributeError:
            pass
        for name in WARMED:
            try:
                getattr(self.client, name)(force=True)
            except CocApiError as exc:
                errors[name] = str(exc)
            except Exception as exc:  # never let the thread die
                errors[name] = f"{type(exc).__name__}: {exc}"
        # Errors the client swallowed while falling back to snapshots.
        errors.update(getattr(self.client, "last_errors", {}) or {})
        self.last_error = errors or None
        self.last_refresh = self.client.freshest_stamp()
        self._ready.set()
        return errors

    @property
    def ready(self):
        """True once the first refresh completed."""
        return self._ready.is_set()

    def status(self):
        """What ``/freshness`` reports instead of a snapshot age."""
        return {
            "mode": "live",
            "ready": self.ready,
            "last_refresh": self.last_refresh,
            "errors": self.last_error,
            "interval_seconds": self.interval,
        }


async def refresh_now(warmer):
    """Force a refresh without stalling the loop. For an admin command."""
    return await asyncio.to_thread(warmer.refresh_once)


async def live_read(reader, method_name, *args, **kwargs):
    """Call ``reader.<method_name>(*args, force=True)`` off the event loop.

    Used by slash commands when real-time data is wanted: runs the blocking
    HTTP call in ``asyncio.to_thread`` so the gateway heartbeat stays responsive
    even on slow endpoints like ``players()`` (~50 requests), while bypassing
    the TTL cache so the caller always receives fresh Supercell data (which
    ``CocClient._cached`` also stores for the dispatcher).

    Degrades transparently when ``reader`` is a ``SnapshotReader`` (no
    ``force`` parameter, local file I/O) or a ``WarmCache`` (forwards to the
    underlying ``CocClient``).
    """
    target = getattr(reader, "client", reader)
    fn = getattr(target, method_name)
    # Only CocClient network endpoints accept force=True; SnapshotReader and
    # local helpers like trends()/age_hours() do not.
    if isinstance(target, CocClient) and method_name in (*WARMED, "members"):
        return await asyncio.to_thread(fn, *args, force=True, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


async def live_context(reader, state, event_key=None):
    """Build a fresh notification context off the event loop.

    Only fetches the endpoint needed by ``event_key`` (``war``, ``raid``,
    ``clan``, or ``meta`` for ``cwl.*``) rather than pulling every endpoint
    including ``players()``, keeping ``/notif test`` and panel samples fast.
    """
    from datetime import datetime, timezone

    group = (event_key or "").split(".", 1)[0]
    needed = {
        "war": ("war",),
        "raid": ("raid", "clan"),
        "clan": ("clan",),
        "cwl": ("meta", "clan"),
    }.get(group, ("war", "raid", "clan", "meta"))

    results = await asyncio.gather(*(live_read(reader, m) for m in needed))
    data = dict(zip(needed, results))
    return {
        "war": data.get("war", {}),
        "raid": data.get("raid", {}),
        "clan": data.get("clan", {}),
        "meta": data.get("meta", {}),
        "reader": reader,
        "now": datetime.now(timezone.utc),
        "prev": state or {},
    }


def build_warm_cache(data_dir, token, clan_tag, base_url=None,
                     cache_seconds=600, interval_seconds=None):
    """``CocClient`` inside a ``WarmCache``, ready to ``start()``."""
    client = CocClient(
        data_dir,
        token=token,
        clan_tag=clan_tag,
        base_url=base_url,
        cache_seconds=cache_seconds,
    )
    return WarmCache(
        client,
        # Refresh a little sooner than the cache expires, so a read never
        # lands in the gap between expiry and the next refresh.
        interval_seconds=interval_seconds or max(60, int(cache_seconds) - 60),
    )