import time
import uuid
from datetime import UTC, datetime

from core.bot import Bot


def find_edges(markets: list[dict], fair: dict, cfg: dict, now: datetime) -> list[dict]:
    """Every (market, side) where our fair value beats the ask by at least min_edge."""
    min_edge = float(cfg.get("min_edge", 0.08))
    lo, hi = float(cfg.get("min_price", 0.05)), float(cfg.get("max_price", 0.95))
    min_minutes = float(cfg.get("min_minutes_left", 30))

    out = []
    for m in markets:
        f = fair.get(m["ticker"])
        if not f:
            continue
        close = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        if (close - now).total_seconds() < min_minutes * 60:
            continue
        p_yes = f["fair"]
        for side, ask, value in (("yes", m.get("yes_ask"), p_yes), ("no", m.get("no_ask"), 1 - p_yes)):
            if ask is None or not lo <= ask <= hi:
                continue
            edge = value - ask
            if edge >= min_edge:
                out.append({
                    "ticker": m["ticker"],
                    "side": side,
                    "price": ask,
                    "fair": round(value, 4),
                    "edge": round(edge, 4),
                    "close_time": m["close_time"],
                    "spot": f.get("spot"),
                })
    return sorted(out, key=lambda s: -s["edge"])


class Watcher(Bot):
    """Compares fair values to Kalshi asks and posts trade ideas to `kalshi:signals`.

    It only suggests. The Risk bot decides whether an idea actually gets traded.
    """

    every = 15

    async def setup(self) -> None:
        self.last_sent: dict[tuple[str, str], float] = {}

    async def run_once(self) -> None:
        book = await self.read("book", max_age=120)
        fair = await self.read("fair", max_age=60)
        if not book or not fair:
            return

        edges = find_edges(book["markets"], fair["markets"], self.config, datetime.now(UTC))
        cooldown = float(self.config.get("cooldown_seconds", 300))
        max_per_run = int(self.config.get("max_signals_per_run", 3))
        count = int(self.config.get("count", 1))

        sent = 0
        now = time.time()
        for e in edges:
            key = (e["ticker"], e["side"])
            if now - self.last_sent.get(key, 0) < cooldown:
                continue
            await self.publish("signals", {"id": uuid.uuid4().hex[:12], "ts": now, "count": count, **e})
            self.last_sent[key] = now
            sent += 1
            if sent >= max_per_run:
                break
        if edges:
            self.log.info("%d markets with edge, sent %d signals", len(edges), sent)
