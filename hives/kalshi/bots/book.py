from core.bot import Bot
from hives.kalshi.kalshi_api import KalshiClient, summarize_market


class KalshiBook(Bot):
    """Pulls open markets (with best bid/ask) from the Kalshi demo for each series.

    Posts to `kalshi:book`:
        {"markets": [{"ticker": ..., "floor": 95749.99, "yes_ask": 0.42, ...}, ...]}
    """

    every = 30

    async def setup(self) -> None:
        self.kalshi = KalshiClient(self.http)

    async def run_once(self) -> None:
        max_hours = float(self.config.get("max_hours", 30))
        markets = []
        for series in self.config.get("series", ["KXBTCD", "KXETHD"]):
            for m in await self.kalshi.markets(series, max_hours):
                s = summarize_market(m)
                s["series"] = series
                markets.append(s)
        # Each snapshot is a few hundred KB, so only keep the last few.
        await self.publish("book", {"markets": markets}, keep=20)
        self.log.debug("%d markets", len(markets))
