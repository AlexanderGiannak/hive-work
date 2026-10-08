import time

from core.bot import Bot
from hives.kalshi.pricing import fair_value, realized_vol

CANDLES_URL = "https://api.exchange.coinbase.com/products/{product}/candles"
VOL_REFRESH_SECONDS = 3600


class Pricer(Bot):
    """Works out a fair YES price for every market in `kalshi:book`.

    Uses the live price from `kalshi:crypto` and volatility from the last few
    days of hourly Coinbase candles. Posts to `kalshi:fair`:
        {"spot": {...}, "vol": {...}, "markets": {"KXBTCD-...": {"fair": 0.61, ...}}}
    """

    every = 15

    async def setup(self) -> None:
        # series ticker -> Coinbase product
        self.underlying = self.config.get("underlying", {"KXBTCD": "BTC-USD", "KXETHD": "ETH-USD"})
        self.default_vol = float(self.config.get("default_vol", 0.6))
        self.vols: dict[str, float] = {}
        self.vols_at = 0.0

    async def refresh_vols(self) -> None:
        for product in set(self.underlying.values()):
            candles = await self.get_json(CANDLES_URL.format(product=product), params={"granularity": 3600})
            # Coinbase returns [time, low, high, open, close, volume], newest first
            closes = [c[4] for c in reversed(candles)]
            vol = realized_vol(closes, 3600)
            if vol:
                self.vols[product] = vol
        self.vols_at = time.time()
        self.log.info("vols: %s", {k: round(v, 3) for k, v in self.vols.items()})

    async def run_once(self) -> None:
        if time.time() - self.vols_at > VOL_REFRESH_SECONDS:
            await self.refresh_vols()

        book = await self.read("book", max_age=120)
        crypto = await self.read("crypto", max_age=60)
        if not book or not crypto:
            self.log.info("waiting for fresh book and crypto prices")
            return

        fair = {}
        for m in book["markets"]:
            product = self.underlying.get(m["series"])
            spot = (crypto.get(product) or {}).get("price")
            if not spot:
                continue
            vol = self.vols.get(product, self.default_vol)
            p = fair_value(m, spot, vol)
            if p is not None:
                fair[m["ticker"]] = {"fair": round(p, 4), "spot": spot, "vol": round(vol, 4)}

        spot = {p: (crypto.get(p) or {}).get("price") for p in set(self.underlying.values())}
        await self.publish("fair", {"spot": spot, "vol": self.vols, "markets": fair}, keep=20)
