"""Postgres helpers. Keeps the history: records, trades, errors, events, metrics."""

import json
import logging
import os
from pathlib import Path
from typing import Any

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://hive:hive@localhost:5432/hive")
SCHEMA = Path(__file__).with_name("schema.sql")

log = logging.getLogger("db")
_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=lambda v: json.dumps(v, default=str), decoder=json.loads, schema="pg_catalog")


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3, init=_init_conn)
    return _pool


async def init_schema() -> None:
    p = await pool()
    async with p.acquire() as conn:
        await conn.execute(SCHEMA.read_text())


async def execute(sql: str, *args: Any) -> str:
    p = await pool()
    return await p.execute(sql, *args)


async def fetch(sql: str, *args: Any) -> list[dict]:
    p = await pool()
    rows = await p.fetch(sql, *args)
    return [dict(r) for r in rows]


async def record(topic: str, data: Any) -> None:
    await execute("INSERT INTO records (topic, data) VALUES ($1, $2)", topic, data)


async def event(hive: str, kind: str, detail: str = "", bot: str | None = None) -> None:
    """Log an event. Never raises, because callers are usually already handling something."""
    try:
        await execute("INSERT INTO events (hive, bot, kind, detail) VALUES ($1, $2, $3, $4)", hive, bot, kind, detail)
    except Exception as e:  # noqa: BLE001
        log.warning("could not log event %s: %s", kind, e)


async def error(hive: str, bot: str, err: str, tb: str = "") -> None:
    try:
        await execute("INSERT INTO errors (hive, bot, error, traceback) VALUES ($1, $2, $3, $4)", hive, bot, err, tb)
    except Exception as e:  # noqa: BLE001
        log.warning("could not log error: %s", e)


async def metric(hive: str, name: str, value: float) -> None:
    await execute("INSERT INTO metrics (hive, name, value) VALUES ($1, $2, $3)", hive, name, value)
