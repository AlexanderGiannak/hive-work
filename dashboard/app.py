"""The dashboard: what every bot is doing, what happened overnight, and the Kalshi scoreboard.

Run locally with Docker Compose and open http://localhost:8000.
On the server the pages are hosted on Vercel, which forwards /api/* calls through
Caddy (HTTPS for hivework.duckdns.org) to this app. There is no login.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import bus, db
from dashboard import kalshi

STATIC = Path(__file__).with_name("static")
log = logging.getLogger("dashboard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for _ in range(30):
        try:
            await bus.client().ping()
            await db.init_schema()
            break
        except Exception as e:  # noqa: BLE001
            log.info("waiting for redis/postgres (%s)", e)
            await asyncio.sleep(2)
    app.state.http = httpx.AsyncClient(timeout=10)
    yield
    await app.state.http.aclose()


app = FastAPI(title="Hivework", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/kalshi")
async def kalshi_page():
    return FileResponse(STATIC / "kalshi.html")


@app.get("/hive/{name}")
async def hive_page(name: str):
    return FileResponse(STATIC / "hive.html")


@app.get("/healthz")
async def healthz():
    await bus.client().ping()
    return {"ok": True}


def bot_status(state: dict, killed: bool, now: float) -> str:
    if killed:
        return "killed"
    if state.get("status") == "stopped":
        return "stopped"
    age = now - float(state.get("heartbeat") or 0)
    if age > float(state.get("timeout") or 120):
        return "stale"
    if state.get("status") == "error":
        return "error"
    return "alive"


@app.get("/api/overview")
async def overview():
    now = time.time()
    kill = await bus.kill_targets()
    bots = []
    for hive, name in await bus.all_bots():
        s = await bus.get_bot_state(hive, name)
        hb = float(s.get("heartbeat") or 0)
        bots.append({
            "hive": hive,
            "name": name,
            "status": bot_status(s, "all" in kill or hive in kill, now),
            "heartbeat_age": round(now - hb, 1) if hb else None,
            "last_run_age": round(now - float(s["last_run"]), 1) if s.get("last_run") else None,
            "every": float(s.get("every") or 0),
            "runs": int(s.get("runs") or 0),
            "errors": int(s.get("errors") or 0),
            "restarts": int(s.get("restarts") or 0),
            "last_error": s.get("last_error") or "",
        })

    queen = await bus.get_bot_state("queen", "queen")
    queen_age = now - float(queen.get("heartbeat") or 0)

    topics = []
    for t in await bus.topics():
        msg = await bus.latest(t)
        if msg:
            topics.append({"topic": t, "age": round(now - msg["ts"], 1)})

    return {
        "now": now,
        "queen": {"alive": queen_age < 30, "heartbeat_age": round(queen_age, 1)},
        "killswitch": kill,
        "hives": sorted({b["hive"] for b in bots}),
        "bots": bots,
        "topics": topics,
    }


@app.get("/api/log")
async def overnight_log(hours: float = 12, hive: str | None = None, limit: int = 300):
    """Everything that happened recently, newest first: restarts, errors, trades, risk blocks."""
    since = timedelta(hours=max(0.0, min(hours, 24 * 14)))
    limit = max(1, min(limit, 1000))
    hive_filter = "AND hive = $2" if hive else ""
    args = [since] + ([hive] if hive else [])
    events = await db.fetch(
        f"SELECT ts, hive, bot, kind, detail FROM events WHERE ts > now() - $1::interval {hive_filter} ORDER BY ts DESC LIMIT {limit}", *args
    )
    errors = await db.fetch(
        f"SELECT ts, hive, bot, 'error' AS kind, error AS detail FROM errors WHERE ts > now() - $1::interval {hive_filter} ORDER BY ts DESC LIMIT {limit}", *args
    )
    trades = await db.fetch(
        f"""SELECT ts, hive, bot, 'trade' AS kind,
                   status || ': ' || side || ' ' || ticker || ' ' || filled || '/' || count || ' @ ' || price || ' (' || mode || ')' AS detail
            FROM trades WHERE ts > now() - $1::interval {hive_filter} ORDER BY ts DESC LIMIT {limit}""",
        *args,
    )
    rows = sorted(events + errors + trades, key=lambda r: r["ts"], reverse=True)[:limit]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"hours": hours, "counts": counts, "rows": rows}


@app.get("/api/topic/{topic}")
async def topic(topic: str, n: int = 1):
    if n <= 1:
        msg = await bus.latest(topic)
        if msg is None:
            raise HTTPException(404, f"nothing on {topic} yet")
        return msg
    return {"messages": await bus.history(topic, min(n, 500))}


@app.get("/api/hive/{hive}/records")
async def records(hive: str, topic: str, hours: float = 24):
    """Recorder history for a topic, oldest first, for charts."""
    full = topic if ":" in topic else f"{hive}:{topic}"
    rows = await db.fetch(
        "SELECT ts, data FROM records WHERE topic = $1 AND ts > now() - $2::interval ORDER BY ts LIMIT 5000", full, timedelta(hours=hours)
    )
    return {"topic": full, "rows": rows}


class KillSwitch(BaseModel):
    target: str = "all"  # "all" or a hive name
    on: bool


@app.post("/api/killswitch")
async def set_killswitch(body: KillSwitch):
    await bus.set_kill(body.target, body.on)
    await db.event(body.target, "killswitch", f"kill switch {'ON' if body.on else 'off'} for {body.target} (from dashboard)")
    return {"killswitch": await bus.kill_targets()}


@app.get("/api/kalshi/markets")
async def kalshi_markets(limit: int = 40):
    return await kalshi.markets_table(limit)


@app.get("/api/kalshi/scoreboard")
async def kalshi_scoreboard():
    return await kalshi.scoreboard(app.state.http)
