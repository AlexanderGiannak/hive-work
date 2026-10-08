"""Feed bots: pull live prices in and post them to the board."""

import asyncio
import json
import os
import time

import websockets

from core.bot import Bot


class CoinbaseFeed(Bot):
    """Live crypto prices from Coinbase's public WebSocket. No key needed.

    Posts a snapshot of every product to `kalshi:crypto` every couple of seconds:
        {"BTC-USD": {"price": 84190.28, "bid": ..., "ask": ..., "time": "..."}, ...}
    """

    every = 0  # nonstop
    timeout = 90
    URL = "wss://ws-feed.exchange.coinbase.com"

    async def run_once(self) -> None:
        products = self.config.get("products", ["BTC-USD", "ETH-USD"])
        publish_every = float(self.config.get("publish_every", 2))
        latest: dict[str, dict] = {}
        last_publish = 0.0

        async with websockets.connect(self.URL, ping_interval=20, max_size=2**20) as ws:
            await ws.send(json.dumps({"type": "subscribe", "product_ids": products, "channels": ["ticker"]}))
            self.log.info("subscribed to %s", ", ".join(products))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except TimeoutError:
                    raise ConnectionError("no data from Coinbase for 60s") from None
                self.heartbeat()

                msg = json.loads(raw)
                if msg.get("type") == "error":
                    raise RuntimeError(f"coinbase: {msg.get('message')} {msg.get('reason', '')}")
                if msg.get("type") != "ticker":
                    continue
                latest[msg["product_id"]] = {
                    "price": float(msg["price"]),
                    "bid": float(msg.get("best_bid") or 0),
                    "ask": float(msg.get("best_ask") or 0),
                    "time": msg.get("time"),
                }
                if time.time() - last_publish >= publish_every:
                    await self.publish("crypto", latest)
                    last_publish = time.time()


class StockFeed(Bot):
    """Stock and ETF quotes from Finnhub's free API (60 calls/minute).

    Get a free key at https://finnhub.io and set FINNHUB_API_KEY in .env.
    Without a key this bot just idles. Posts to `kalshi:stocks`.
    """

    every = 60
    URL = "https://finnhub.io/api/v1/quote"

    async def setup(self) -> None:
        self.key = os.environ.get("FINNHUB_API_KEY", "")
        if not self.key:
            self.log.warning("FINNHUB_API_KEY not set, stock feed is idle")

    async def run_once(self) -> None:
        if not self.key:
            return
        quotes = {}
        for symbol in self.config.get("symbols", ["SPY", "QQQ"]):
            q = await self.get_json(self.URL, params={"symbol": symbol}, headers={"X-Finnhub-Token": self.key})
            if q.get("c"):
                quotes[symbol] = {"price": q["c"], "change_pct": q.get("dp"), "prev_close": q.get("pc"), "time": q.get("t")}
        if quotes:
            await self.publish("stocks", quotes)
