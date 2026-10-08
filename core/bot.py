"""The Bot class every bot uses.

A periodic bot sets `every` and writes `run_once`:

    class QuakeFeed(Bot):
        every = 60

        async def run_once(self):
            quakes = await self.get_json("https://earthquake.usgs.gov/...")
            await self.publish("quakes", quakes)

A nonstop bot (like a WebSocket feed) sets `every = 0`, loops forever inside
`run_once`, and calls `self.heartbeat()` every few seconds. If it stops calling
heartbeat for longer than `timeout` seconds, the queen restarts it.

Settings from hive.yml show up in `self.config`. `every` and `timeout` can be
overridden there too.
"""

import asyncio
import logging
import re
import time
import traceback
from collections.abc import AsyncIterator
from typing import Any

import httpx

from core import alerts, bus, db

# Consecutive failures before we ping Discord.
ALERT_AFTER_FAILURES = 3
MAX_BACKOFF = 300
HEARTBEAT_FLUSH_SECONDS = 2


class RateLimited(Exception):
    """An API kept answering 429 after we backed off."""


def snake_case(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class Bot:
    name: str = ""  # defaults to the class name in snake_case
    every: float = 60  # seconds between run_once calls; 0 means run_once loops forever
    timeout: float = 120  # no heartbeat for this long and the queen restarts us

    def __init__(self, hive: str, config: dict | None = None):
        self.hive = hive
        self.config = dict(config or {})
        self.name = self.name or snake_case(type(self).__name__)
        self.every = float(self.config.get("every", self.every))
        self.timeout = float(self.config.get("timeout", self.timeout))
        self.log = logging.getLogger(f"{hive}.{self.name}")
        self._last_beat = time.time()
        self._http: httpx.AsyncClient | None = None

    # Override these

    async def setup(self) -> None:
        """Runs once before the first run_once."""

    async def run_once(self) -> None:
        raise NotImplementedError

    async def teardown(self) -> None:
        """Runs once when the bot is stopped."""

    # Board helpers

    def topic(self, topic: str) -> str:
        """`prices` becomes `kalshi:prices`. Full names like `kalshi:prices` pass through."""
        return topic if ":" in topic else f"{self.hive}:{topic}"

    async def publish(self, topic: str, data: Any, keep: int = bus.STREAM_MAXLEN) -> None:
        """Post to the board. Use a small `keep` for big snapshots so Redis doesn't fill up."""
        full = self.topic(topic)
        if not full.startswith(f"{self.hive}:"):
            raise ValueError(f"{self.name} can only publish to {self.hive}:* topics, not {full}")
        await bus.publish(full, data, keep)

    async def read(self, topic: str, max_age: float | None = None) -> Any:
        """Latest data on a topic, or None if there's nothing (or it's older than max_age seconds)."""
        msg = await bus.latest(self.topic(topic))
        if msg is None:
            return None
        if max_age is not None and time.time() - msg["ts"] > max_age:
            return None
        return msg["data"]

    async def listen(self, topic: str) -> AsyncIterator[Any]:
        """Yield each new message's data as it arrives. Heartbeats for you while waiting."""
        async for msg in bus.listen(self.topic(topic)):
            self.heartbeat()
            if msg is not None:
                yield msg["data"]

    def heartbeat(self) -> None:
        """Tell the queen we're alive. Periodic bots get this for free."""
        self._last_beat = time.time()

    async def alert(self, message: str, channel: str = "alerts") -> None:
        await alerts.send(f"**{self.hive}/{self.name}**: {message}", channel)

    # HTTP with polite 429 handling

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=20, headers={"User-Agent": "Hivework/1.0 (student project)"})
        return self._http

    async def get_json(self, url: str, params: dict | None = None, headers: dict | None = None, retries: int = 3) -> Any:
        """GET a URL and return its JSON. Backs off and retries on 429 like the rules say."""
        delay = 5.0
        for attempt in range(retries + 1):
            resp = await self.http.get(url, params=params, headers=headers)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            if attempt == retries:
                break
            wait = float(resp.headers.get("Retry-After") or delay)
            self.log.warning("429 from %s, waiting %.0fs", url, wait)
            await self._sleep(wait)
            delay = min(delay * 2, MAX_BACKOFF)
        raise RateLimited(url)

    # The main loop. You shouldn't need to touch anything below.

    async def _sleep(self, seconds: float) -> None:
        """Sleep in small pieces so heartbeats keep going during long waits."""
        end = time.time() + seconds
        while (left := end - time.time()) > 0:
            self.heartbeat()
            await asyncio.sleep(min(left, HEARTBEAT_FLUSH_SECONDS))

    async def _flush_heartbeats(self) -> None:
        while True:
            await bus.heartbeat_at(self.hive, self.name, self._last_beat)
            await asyncio.sleep(HEARTBEAT_FLUSH_SECONDS)

    async def run(self) -> None:
        await bus.register_bot(self.hive, self.name)
        await bus.set_bot_state(self.hive, self.name, status="starting", every=self.every, timeout=self.timeout, last_error="")
        flusher = asyncio.create_task(self._flush_heartbeats())
        failures = 0
        try:
            await self.setup()
            await bus.set_bot_state(self.hive, self.name, status="running")
            while True:
                self.heartbeat()
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    failures += 1
                    await self._record_failure(e, failures)
                    backoff = min(MAX_BACKOFF, max(self.every, 5) * 2 ** min(failures - 1, 6))
                    if isinstance(e, RateLimited):
                        backoff = MAX_BACKOFF
                    await self._sleep(backoff)
                    continue

                if failures:
                    if failures >= ALERT_AFTER_FAILURES:
                        await self.alert(f"recovered after {failures} failures")
                    failures = 0
                await bus.incr_bot_state(self.hive, self.name, "runs")
                await bus.set_bot_state(self.hive, self.name, status="running", last_run=time.time())
                await self._sleep(self.every if self.every > 0 else 1)
        finally:
            flusher.cancel()
            await bus.set_bot_state(self.hive, self.name, status="stopped")
            try:
                await self.teardown()
            finally:
                if self._http is not None:
                    await self._http.aclose()

    async def _record_failure(self, e: Exception, failures: int) -> None:
        err = f"{type(e).__name__}: {e}"
        self.log.error("run failed (%d in a row): %s", failures, err)
        await bus.incr_bot_state(self.hive, self.name, "errors")
        await bus.set_bot_state(self.hive, self.name, status="error", last_error=err[:500], last_error_at=time.time())
        await db.error(self.hive, self.name, err, traceback.format_exc())
        if failures == ALERT_AFTER_FAILURES:
            await self.alert(f"failing: {err}")
