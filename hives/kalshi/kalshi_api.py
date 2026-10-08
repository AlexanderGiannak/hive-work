"""Small Kalshi API client. Demo only, on purpose.

Market data (markets, order books) is public and needs no key. Placing orders
needs a demo API key: make one at https://demo.kalshi.co (Account > API keys),
save the private key file somewhere outside the repo, and set KALSHI_KEY_ID and
KALSHI_PRIVATE_KEY_PATH in .env. Without a key, the Trader paper trades instead.
"""

import base64
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"


def dollars(value) -> float:
    """Kalshi sends prices as strings like "0.4500". Missing means 0."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _price(value) -> float | None:
    """An ask or bid only counts if it's strictly between 0 and 1."""
    p = dollars(value)
    return p if 0 < p < 1 else None


def summarize_market(m: dict) -> dict:
    """Keep just the fields the other bots need."""
    return {
        "ticker": m["ticker"],
        "event": m.get("event_ticker"),
        "title": m.get("title"),
        "subtitle": m.get("yes_sub_title") or m.get("subtitle"),
        "strike_type": m.get("strike_type"),
        "floor": m.get("floor_strike"),
        "cap": m.get("cap_strike"),
        "close_time": m.get("close_time"),
        "yes_bid": _price(m.get("yes_bid_dollars")),
        "yes_ask": _price(m.get("yes_ask_dollars")),
        "no_bid": _price(m.get("no_bid_dollars")),
        "no_ask": _price(m.get("no_ask_dollars")),
        "last": dollars(m.get("last_price_dollars")),
        "volume_24h": dollars(m.get("volume_24h_fp")),
        "status": m.get("status"),
        "result": m.get("result") or None,
    }


class KalshiClient:
    def __init__(self, http: httpx.AsyncClient, base: str | None = None):
        self.http = http
        self.base = (base or os.environ.get("KALSHI_API_BASE") or DEMO_BASE).rstrip("/")
        if "demo" not in self.base:
            # Rule 3: fake money only.
            raise RuntimeError(f"refusing to use a non-demo Kalshi API: {self.base}")
        self.key_id = os.environ.get("KALSHI_KEY_ID", "")
        self._shards: dict[str, int] = {}  # ticker -> exchange_index
        self._key = None
        key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
        if self.key_id and key_path and Path(key_path).is_file():
            self._key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)

    @property
    def can_trade(self) -> bool:
        return self._key is not None

    def _sign_headers(self, method: str, url: str) -> dict:
        ts = str(int(time.time() * 1000))
        path = urlparse(url).path  # signature covers the path without the query string
        message = f"{ts}{method.upper()}{path}".encode()
        if isinstance(self._key, rsa.RSAPrivateKey):
            sig = self._key.sign(
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
        elif isinstance(self._key, ed25519.Ed25519PrivateKey):
            sig = self._key.sign(message)
        else:
            raise RuntimeError("unsupported Kalshi key type")
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }

    async def _request(self, method: str, path: str, *, auth: bool = False, **kwargs) -> dict:
        url = f"{self.base}{path}"
        headers = self._sign_headers(method, url) if auth else {}
        resp = await self.http.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # Public market data

    async def markets(self, series: str, max_hours: float, max_pages: int = 5) -> list[dict]:
        """Open markets in a series that close within the next `max_hours`."""
        now = int(time.time())
        params = {"series_ticker": series, "status": "open", "limit": 1000, "min_close_ts": now, "max_close_ts": now + int(max_hours * 3600)}
        out: list[dict] = []
        for _ in range(max_pages):
            data = await self._request("GET", "/markets", params=params)
            out.extend(data.get("markets", []))
            cursor = data.get("cursor")
            if not cursor:
                break
            params["cursor"] = cursor
        return out

    async def market(self, ticker: str) -> dict:
        return (await self._request("GET", f"/markets/{ticker}"))["market"]

    async def shard(self, ticker: str) -> int:
        """Which exchange shard a market trades on. Orders must go there, and so must the money.

        Kalshi splits markets across shards by category (crypto is on shard 2) and each
        shard has its own balance. See https://docs.kalshi.com/getting_started/exchange_sharding
        """
        if ticker not in self._shards:
            self._shards[ticker] = int((await self.market(ticker)).get("exchange_index") or 0)
        return self._shards[ticker]

    # Trading (needs a key)

    async def buy(self, ticker: str, side: str, count: int, price: float) -> dict:
        """Immediate-or-cancel limit buy of YES or NO at `price` or better. Cancels whatever doesn't fill.

        The V2 order endpoint quotes everything from the YES side: buying YES is a
        "bid" at the YES price, and buying NO at p is an "ask" (sell YES) at 1 - p.
        Returns the order id, how many filled, and the average price we paid for
        the side we bought (None if nothing filled).
        """
        if side not in ("yes", "no"):
            raise ValueError(f"side must be 'yes' or 'no', not {side!r}")
        yes_price = price if side == "yes" else 1 - price
        body = {
            "ticker": ticker,
            "side": "bid" if side == "yes" else "ask",
            "count": f"{count:.2f}",
            "price": f"{yes_price:.4f}",
            "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": str(uuid.uuid4()),
            "exchange_index": await self.shard(ticker),
        }
        resp = await self._request("POST", "/portfolio/events/orders", auth=True, json=body)
        filled = int(dollars(resp.get("fill_count")))
        avg_yes = dollars(resp.get("average_fill_price"))
        avg = None
        if filled and avg_yes:
            avg = avg_yes if side == "yes" else 1 - avg_yes
        return {"order_id": resp.get("order_id"), "filled": filled, "avg_price": avg, "raw": resp}

    async def balance(self) -> dict:
        return await self._request("GET", "/portfolio/balance", auth=True)
