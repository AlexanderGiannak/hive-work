import time
from dataclasses import dataclass

from core import bus, db
from core.bot import Bot

DEFAULT_LIMITS = {
    "min_edge": 0.05,
    "min_price": 0.05,
    "max_price": 0.95,
    "max_signal_age": 30,  # seconds
    "max_contracts_per_market": 10,
    "max_exposure": 100.0,  # dollars spent in the last 24h
    "max_orders_per_hour": 20,
    "cooldown_seconds": 300,  # between orders on the same market
}


@dataclass
class RiskState:
    position: int  # contracts we already hold in this market (any side)
    exposure: float  # dollars spent in the last 24h
    orders_last_hour: int
    last_order_at: float  # unix time of our last order in this market, 0 if never


def check(signal: dict, state: RiskState, limits: dict, now: float) -> str | None:
    """Return why a signal should be blocked, or None if it's fine to trade."""
    price, count = float(signal["price"]), int(signal["count"])
    if count < 1:
        return "count must be at least 1"
    if now - float(signal["ts"]) > limits["max_signal_age"]:
        return f"signal is stale ({now - float(signal['ts']):.0f}s old)"
    if not limits["min_price"] <= price <= limits["max_price"]:
        return f"price {price:.2f} outside {limits['min_price']:.2f}-{limits['max_price']:.2f}"
    if float(signal["edge"]) < limits["min_edge"]:
        return f"edge {signal['edge']:.3f} below {limits['min_edge']}"
    if state.position + count > limits["max_contracts_per_market"]:
        return f"would hold {state.position + count} contracts, max is {limits['max_contracts_per_market']}"
    if state.exposure + price * count > limits["max_exposure"]:
        return f"would spend ${state.exposure + price * count:.2f} in 24h, max is ${limits['max_exposure']:.2f}"
    if state.orders_last_hour >= limits["max_orders_per_hour"]:
        return f"already sent {state.orders_last_hour} orders this hour"
    if now - state.last_order_at < limits["cooldown_seconds"]:
        return f"traded this market {now - state.last_order_at:.0f}s ago, cooldown is {limits['cooldown_seconds']}s"
    return None


class Risk(Bot):
    """Checks every signal against our limits before anything gets traded.

    Approved signals go to `kalshi:orders` for the Trader. Blocked ones go to
    `kalshi:blocked` and the overnight log, with the reason.
    """

    every = 0

    async def setup(self) -> None:
        self.limits = {**DEFAULT_LIMITS, **self.config.get("limits", {})}
        # Approvals from the last few seconds the Trader may not have written to Postgres yet.
        self.pending: list[dict] = []

    async def state_for(self, ticker: str, now: float) -> RiskState:
        self.pending = [p for p in self.pending if now - p["approved_at"] < 15]
        rows = await db.fetch(
            """
            SELECT
              COALESCE(SUM(filled) FILTER (WHERE ticker = $2), 0) AS position,
              COALESCE(SUM(filled * price) FILTER (WHERE ts > now() - interval '24 hours'), 0) AS exposure,
              COUNT(*) FILTER (WHERE ts > now() - interval '1 hour') AS orders_last_hour,
              EXTRACT(EPOCH FROM MAX(ts) FILTER (WHERE ticker = $2)) AS last_order_at
            FROM trades WHERE hive = $1 AND action = 'buy'
            """,
            self.hive,
            ticker,
        )
        r = rows[0]
        mine = [p for p in self.pending if p["ticker"] == ticker]
        return RiskState(
            position=int(r["position"]) + sum(p["count"] for p in mine),
            exposure=float(r["exposure"]) + sum(p["price"] * p["count"] for p in self.pending),
            orders_last_hour=int(r["orders_last_hour"]) + len(self.pending),
            last_order_at=max([float(r["last_order_at"] or 0)] + [p["approved_at"] for p in mine]),
        )

    async def run_once(self) -> None:
        async for signal in self.listen("signals"):
            now = time.time()
            if await bus.killed(self.hive):
                reason = "kill switch is on"
            else:
                reason = check(signal, await self.state_for(signal["ticker"], now), self.limits, now)

            if reason:
                await self.publish("blocked", {**signal, "reason": reason})
                await db.event(self.hive, "risk_block", f"{signal['ticker']} {signal['side']} @ {signal['price']:.2f}: {reason}", bot=self.name)
                self.log.info("blocked %s %s: %s", signal["ticker"], signal["side"], reason)
                continue

            approved = {**signal, "approved_at": now}
            self.pending.append(approved)
            await self.publish("orders", approved)
            self.log.info("approved %s %s x%d @ %.2f (fair %.2f)", signal["ticker"], signal["side"], signal["count"], signal["price"], signal["fair"])
