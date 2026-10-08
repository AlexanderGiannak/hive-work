import time

import httpx

from core import bus, db
from core.bot import Bot
from hives.kalshi.kalshi_api import KalshiClient


class Trader(Bot):
    """Places orders the Risk bot approved, on the Kalshi demo (fake money).

    With a demo API key in .env it sends real demo orders. Without one it
    paper trades: it pretends the order filled at the ask and records it the
    same way, so the scoreboard works on your laptop.
    """

    every = 0

    async def setup(self) -> None:
        self.kalshi = KalshiClient(self.http)
        self.mode = "demo" if self.kalshi.can_trade else "paper"
        self.log.info("trading mode: %s", self.mode)

    async def run_once(self) -> None:
        async for order in self.listen("orders"):
            if await bus.killed(self.hive):
                self.log.warning("kill switch on, dropping order for %s", order["ticker"])
                continue
            if time.time() - order["approved_at"] > 30:
                self.log.warning("order for %s is stale, dropping it", order["ticker"])
                continue
            await self.place(order)

    async def place(self, o: dict) -> None:
        ticker, side, count, price = o["ticker"], o["side"], int(o["count"]), float(o["price"])
        order_id, detail = None, {}

        if self.mode == "paper":
            filled, status = count, "filled"
        else:
            try:
                resp = await self.kalshi.buy(ticker, side, count, price)
            except httpx.HTTPStatusError as e:
                detail = {"error": e.response.text[:500]}
                filled, status = 0, "error"
                self.log.error("order rejected for %s: %s", ticker, detail["error"])
            else:
                order_id, filled = resp["order_id"], resp["filled"]
                if resp["avg_price"] is not None:
                    price = resp["avg_price"]
                status = "filled" if filled == count else "partial" if filled else "unfilled"
                detail = {"kalshi": resp["raw"]}

        await db.execute(
            """INSERT INTO trades (hive, bot, mode, ticker, side, action, count, filled, price, fair, order_id, status, detail)
               VALUES ($1, $2, $3, $4, $5, 'buy', $6, $7, $8, $9, $10, $11, $12)""",
            self.hive, self.name, self.mode, ticker, side, count, filled, round(price, 4), o.get("fair"), order_id, status, detail,
        )
        fill = {"ticker": ticker, "side": side, "count": count, "filled": filled, "price": round(price, 4), "fair": o.get("fair"), "status": status, "mode": self.mode}
        await self.publish("fills", fill)
        self.log.info("%s: %s %s %d/%d @ %.2f", status, ticker, side, filled, count, price)
        if filled:
            await self.alert(f"bought {filled}x {side.upper()} {ticker} @ ${price:.2f} (fair {o.get('fair', 0):.2f}, {self.mode})", "trades")
