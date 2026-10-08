"""The queen: starts every bot in each hive.yml and keeps them alive.

Each bot runs in its own process, so one stuck bot can't freeze the others.
Every few seconds the queen checks each one:

- process exited          -> start it again (waiting longer if it keeps crashing)
- no heartbeat in timeout -> kill it, then start it again
- kill switch is on       -> stop it and leave it stopped until the switch is off

Run it with `python -m core.queen`. Docker Compose does this for you.
"""

import asyncio
import logging
import signal
import sys
import time
from dataclasses import dataclass

from core import alerts, bus, db
from core.hive import enabled_hives, find_bot_class, load_hive
from core.runner import setup_logging

CHECK_SECONDS = 5
STATUS_LOG_SECONDS = 30
STOP_GRACE_SECONDS = 10
# A bot that crashes this many times inside CRASH_WINDOW waits longer before each restart.
CRASH_WINDOW = 600
MAX_RESTART_DELAY = 300

log = logging.getLogger("queen")


@dataclass
class Worker:
    hive: str
    cls_name: str
    name: str
    timeout: float
    proc: asyncio.subprocess.Process | None = None
    started_at: float = 0.0
    next_start: float = 0.0
    crashes: list[float] | None = None
    stopped_by_switch: bool = False

    @property
    def label(self) -> str:
        return f"{self.hive}/{self.name}"

    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None


class Queen:
    def __init__(self) -> None:
        self.workers: list[Worker] = []
        self._stopping = False

    def load(self) -> None:
        for hive_name in enabled_hives():
            try:
                hive = load_hive(hive_name)
            except Exception as e:  # noqa: BLE001
                log.error("could not load hives/%s/hive.yml: %s", hive_name, e)
                continue
            for spec in hive.bots:
                try:
                    cls = find_bot_class(hive.name, spec.cls_name)
                    bot = cls(hive.name, spec.config)
                except Exception as e:  # noqa: BLE001
                    log.error("skipping %s/%s: %s", hive.name, spec.cls_name, e)
                    continue
                self.workers.append(Worker(hive.name, spec.cls_name, bot.name, bot.timeout, crashes=[]))
        log.info("loaded %d bots from hives: %s", len(self.workers), ", ".join(sorted({w.hive for w in self.workers})) or "none")

    async def start(self, w: Worker) -> None:
        w.proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "core.runner", w.hive, w.cls_name)
        w.started_at = time.time()
        await bus.register_bot(w.hive, w.name)
        await bus.set_bot_state(w.hive, w.name, pid=w.proc.pid, started_at=w.started_at, heartbeat=w.started_at)
        log.info("started %s (pid %d)", w.label, w.proc.pid)

    async def stop(self, w: Worker, reason: str) -> None:
        if not w.running():
            return
        log.info("stopping %s: %s", w.label, reason)
        w.proc.terminate()
        try:
            await asyncio.wait_for(w.proc.wait(), STOP_GRACE_SECONDS)
        except TimeoutError:
            w.proc.kill()
            await w.proc.wait()

    def _restart_delay(self, w: Worker) -> float:
        now = time.time()
        w.crashes = [t for t in w.crashes if now - t < CRASH_WINDOW] + [now]
        n = len(w.crashes)
        return 0 if n <= 2 else min(MAX_RESTART_DELAY, 5 * 2 ** (n - 3))

    async def restart(self, w: Worker, why: str) -> None:
        delay = self._restart_delay(w)
        w.next_start = time.time() + delay
        restarts = await bus.incr_bot_state(w.hive, w.name, "restarts")
        msg = f"{why}, restarting" + (f" in {delay:.0f}s" if delay else "")
        log.warning("%s %s", w.label, msg)
        await db.event(w.hive, "restart", msg, bot=w.name)
        await alerts.send(f"**{w.label}** {msg} (restart #{restarts})")

    async def check(self, w: Worker) -> None:
        now = time.time()

        # The dashboard logs the switch flipping, so no per-bot events here.
        if await bus.killed(w.hive):
            if w.running():
                await self.stop(w, "kill switch on")
            w.proc = None
            w.stopped_by_switch = True
            return
        if w.stopped_by_switch:
            log.info("kill switch off, starting %s again", w.label)
            w.stopped_by_switch = False
            w.next_start = 0

        if w.proc is not None and w.proc.returncode is not None:
            code = w.proc.returncode
            w.proc = None
            await self.restart(w, f"exited with code {code}")

        if w.proc is None:
            if time.time() >= w.next_start:
                await self.start(w)
            return

        state = await bus.get_bot_state(w.hive, w.name)
        last = max(float(state.get("heartbeat") or 0), w.started_at)
        if now - last > w.timeout:
            await self.stop(w, f"no heartbeat for {now - last:.0f}s")
            w.proc = None
            await self.restart(w, f"missed heartbeats for {now - last:.0f}s")

    async def run(self) -> None:
        await self._wait_for_services()
        self.load()
        await db.event("queen", "start", f"queen up with {len(self.workers)} bots")

        last_status = 0.0
        while not self._stopping:
            for w in self.workers:
                try:
                    await self.check(w)
                except Exception as e:  # noqa: BLE001
                    log.exception("check failed for %s: %s", w.label, e)

            await bus.set_bot_state("queen", "queen", heartbeat=time.time(), status="running")
            if time.time() - last_status >= STATUS_LOG_SECONDS:
                alive = sum(w.running() for w in self.workers)
                killed = await bus.kill_targets()
                log.info("heartbeat: %d/%d bots alive%s", alive, len(self.workers), f", kill switch: {killed}" if killed else "")
                last_status = time.time()
            await asyncio.sleep(CHECK_SECONDS)

    async def shutdown(self) -> None:
        self._stopping = True
        await asyncio.gather(*(self.stop(w, "queen shutting down") for w in self.workers))
        await bus.set_bot_state("queen", "queen", status="stopped")

    async def _wait_for_services(self) -> None:
        for _attempt in range(30):
            try:
                await bus.client().ping()
                await db.init_schema()
                return
            except Exception as e:  # noqa: BLE001
                log.info("waiting for redis/postgres (%s)", e)
                await asyncio.sleep(2)
        raise SystemExit("redis/postgres never came up")


async def main() -> None:
    queen = Queen()
    task = asyncio.create_task(queen.run())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        await queen.shutdown()
        log.info("queen stopped")


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
