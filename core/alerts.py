"""Discord alerts.

Set DISCORD_WEBHOOK_URL in .env to post to #alerts. Extra channels can have
their own webhook: DISCORD_WEBHOOK_TRADES posts when channel="trades".
With no webhook set, alerts just go to the log, which is what you want locally.
"""

import logging
import os
import time

import httpx

log = logging.getLogger("alerts")

# Don't send the same message more than once per this many seconds.
DEDUPE_SECONDS = 300
_recent: dict[str, float] = {}


def _webhook(channel: str) -> str:
    specific = os.environ.get(f"DISCORD_WEBHOOK_{channel.upper()}", "")
    return specific or os.environ.get("DISCORD_WEBHOOK_URL", "")


async def send(message: str, channel: str = "alerts") -> bool:
    """Post a message. Returns True if Discord accepted it."""
    now = time.time()
    key = f"{channel}:{message}"
    if now - _recent.get(key, 0) < DEDUPE_SECONDS:
        return False
    _recent[key] = now

    url = _webhook(channel)
    if not url:
        log.info("[alert:%s] %s", channel, message)
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(url, json={"content": message[:1900]})
        if resp.status_code == 429:
            log.warning("discord rate limited us, dropping alert: %s", message)
            return False
        resp.raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.warning("discord alert failed (%s): %s", e, message)
        return False
