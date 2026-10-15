from core.bot import Bot
from hives.kalshi.kalshi_api import KalshiClient


class KalshiAccount(Bot):
    """Posts the demo account's cash and position value, straight from Kalshi, to `kalshi:account`.

    This is the scoreboard's source of truth. Adding up our own trades drifts from
    it: Kalshi charges fees, and it pays out $1 right away when we end up holding
    YES and NO in the same market. Only runs with a demo key (not in paper mode).
    """

    every = 60

    async def setup(self) -> None:
        self.kalshi = KalshiClient(self.http)
        self.start = float(self.config.get("start_balance", 100))

    async def run_once(self) -> None:
        if not self.kalshi.can_trade:
            return
        b = await self.kalshi.balance()
        cash = float(b["balance_dollars"])
        positions = b["portfolio_value"] / 100  # Kalshi sends this one in cents
        total = cash + positions
        await self.publish("account", {
            "cash": round(cash, 2),
            "positions": round(positions, 2),
            "total": round(total, 2),
            "start": self.start,
            "pnl": round(total - self.start, 2),
        }, keep=100)
