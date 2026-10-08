import asyncio
import json

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from hives.kalshi.kalshi_api import KalshiClient


def place(side, price, response):
    """Run KalshiClient.buy against a fake Kalshi and return (request body, result)."""
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":  # the shard lookup
            return httpx.Response(200, json={"market": {"ticker": "T", "exchange_index": 2}})
        sent["path"] = request.url.path
        sent["body"] = json.loads(request.content)
        return httpx.Response(201, json=response)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = KalshiClient(http)
            client.key_id, client._key = "test", ed25519.Ed25519PrivateKey.generate()
            return await client.buy("T", side, 2, price)

    result = asyncio.run(go())
    return sent, result


def test_buy_yes_is_a_bid_at_the_yes_price():
    sent, result = place("yes", 0.40, {"order_id": "o1", "fill_count": "2.00", "remaining_count": "0.00", "average_fill_price": "0.38"})
    assert sent["path"].endswith("/portfolio/events/orders")
    assert sent["body"]["side"] == "bid"
    assert sent["body"]["price"] == "0.4000"
    assert sent["body"]["count"] == "2.00"
    assert sent["body"]["exchange_index"] == 2
    assert result["filled"] == 2
    assert result["avg_price"] == 0.38


def test_buy_no_is_an_ask_at_one_minus_price():
    sent, result = place("no", 0.55, {"order_id": "o2", "fill_count": "1.00", "remaining_count": "1.00", "average_fill_price": "0.46"})
    assert sent["body"]["side"] == "ask"
    assert sent["body"]["price"] == "0.4500"
    assert result["filled"] == 1
    assert abs(result["avg_price"] - 0.54) < 1e-9


def test_unfilled_order_has_no_price():
    _, result = place("no", 0.55, {"order_id": "o3", "fill_count": "0.00", "remaining_count": "2.00"})
    assert result["filled"] == 0
    assert result["avg_price"] is None
