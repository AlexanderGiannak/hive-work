"""Redis helpers for the shared board.

Every topic is a Redis stream stored at `board:<topic>`, capped so it never
grows forever. Topic names always start with the hive name, like `kalshi:book`.

Bot state lives in a hash per bot at `bot:<hive>:<name>`. The bot writes its
heartbeat and run counts there, the queen writes pid and restart counts, and
the dashboard reads all of it.
"""

import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
STREAM_MAXLEN = 1000
TOPICS_KEY = "board:topics"
BOTS_KEY = "bots"

_client: redis.Redis | None = None


def client() -> redis.Redis:
    global _client
    if _client is None:
        # The read timeout has to be longer than listen()'s blocking reads.
        _client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=30, health_check_interval=30)
    return _client


def stream_key(topic: str) -> str:
    return f"board:{topic}"


def bot_key(hive: str, name: str) -> str:
    return f"bot:{hive}:{name}"


async def publish(topic: str, data: Any, keep: int = STREAM_MAXLEN) -> str:
    """Post data to the board, keeping roughly the last `keep` messages. Returns the stream message id."""
    r = client()
    payload = json.dumps({"ts": time.time(), "data": data}, default=str)
    msg_id = await r.xadd(stream_key(topic), {"m": payload}, maxlen=keep, approximate=True)
    await r.sadd(TOPICS_KEY, topic)
    return msg_id


def _decode(fields: dict) -> dict:
    return json.loads(fields["m"])


async def latest(topic: str) -> dict | None:
    """Most recent message on a topic as {"ts": ..., "data": ...}, or None."""
    rows = await client().xrevrange(stream_key(topic), count=1)
    if not rows:
        return None
    return _decode(rows[0][1])


async def history(topic: str, count: int = 100) -> list[dict]:
    """Up to `count` recent messages, oldest first."""
    rows = await client().xrevrange(stream_key(topic), count=count)
    return [_decode(fields) for _, fields in reversed(rows)]


async def listen(topic: str, from_now: bool = True, block_ms: int = 5000) -> AsyncIterator[dict | None]:
    """Yield new messages on a topic as they arrive.

    Yields None every `block_ms` when nothing arrives, so a nonstop bot can
    send a heartbeat while it waits.
    """
    last_id = "$" if from_now else "0"
    r = client()
    while True:
        resp = await r.xread({stream_key(topic): last_id}, count=100, block=block_ms)
        if not resp:
            yield None
            continue
        for _, rows in resp:
            for msg_id, fields in rows:
                last_id = msg_id
                yield _decode(fields)


async def topics() -> list[str]:
    return sorted(await client().smembers(TOPICS_KEY))


# Bot state


async def register_bot(hive: str, name: str) -> None:
    await client().sadd(BOTS_KEY, f"{hive}:{name}")


async def set_bot_state(hive: str, name: str, **fields: Any) -> None:
    clean = {k: ("" if v is None else str(v)) for k, v in fields.items()}
    await client().hset(bot_key(hive, name), mapping=clean)


async def incr_bot_state(hive: str, name: str, field: str, amount: int = 1) -> int:
    return await client().hincrby(bot_key(hive, name), field, amount)


async def get_bot_state(hive: str, name: str) -> dict:
    return await client().hgetall(bot_key(hive, name))


async def heartbeat_at(hive: str, name: str, ts: float | None = None) -> None:
    await client().hset(bot_key(hive, name), "heartbeat", str(ts or time.time()))


async def all_bots() -> list[tuple[str, str]]:
    members = await client().smembers(BOTS_KEY)
    return sorted(tuple(m.split(":", 1)) for m in members)


# Kill switch: "all" stops every hive, a hive name stops just that hive.

KILL_KEY = "killswitch"


async def killed(hive: str) -> bool:
    return bool(await client().sismember(KILL_KEY, "all")) or bool(await client().sismember(KILL_KEY, hive))


async def set_kill(target: str, on: bool) -> None:
    if on:
        await client().sadd(KILL_KEY, target)
    else:
        await client().srem(KILL_KEY, target)


async def kill_targets() -> list[str]:
    return sorted(await client().smembers(KILL_KEY))
