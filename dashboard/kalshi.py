"""Kalshi scoreboard and market table for the dashboard."""

import time

import httpx

from core import bus, db
from hives.kalshi.kalshi_api import KalshiClient, summarize_market

# Settled results never change, so remember them.
_settled: dict[str, str] = {}
# Closed-but-not-settled lookups get refreshed at most this often.
_checked: dict[str, tuple[float, dict]] = {}
RECHECK_SECONDS = 300


async def markets_table(limit: int) -> dict:
    """Kalshi prices next to our fair values, biggest gaps first."""
    book = await bus.latest("kalshi:book")
    fair = await bus.latest("kalshi:fair")
    if not book:
        return {"rows": [], "spot": {}, "book_age": None, "fair_age": None}
    fair_markets = fair["data"]["markets"] if fair else {}

    rows = []
    for m in book["data"]["markets"]:
        f = fair_markets.get(m["ticker"])
        p = f["fair"] if f else None
        gap = None
        if p is not None:
            gaps = []
            if m.get("yes_ask"):
                gaps.append(p - m["yes_ask"])
            if m.get("no_ask"):
                gaps.append((1 - p) - m["no_ask"])
            gap = max(gaps) if gaps else None
        rows.append({**m, "fair": p, "gap": gap})

    rows.sort(key=lambda r: (r["gap"] is None, -(r["gap"] or 0)))
    now = time.time()
    return {
        "rows": rows[:limit],
        "total": len(rows),
        "spot": fair["data"]["spot"] if fair else {},
        "book_age": round(now - book["ts"], 1),
        "fair_age": round(now - fair["ts"], 1) if fair else None,
    }


async def _market_info(client: KalshiClient, ticker: str) -> dict | None:
    if ticker in _settled:
        return {"result": _settled[ticker]}
    hit = _checked.get(ticker)
    if hit and time.time() - hit[0] < RECHECK_SECONDS:
        return hit[1]
    try:
        info = summarize_market(await client.market(ticker))
    except httpx.HTTPError:
        return hit[1] if hit else None
    if info.get("result") in ("yes", "no"):
        _settled[ticker] = info["result"]
    _checked[ticker] = (time.time(), info)
    return info


async def scoreboard(http: httpx.AsyncClient) -> dict:
    positions = await db.fetch(
        """SELECT ticker, side, mode, SUM(filled) AS contracts, SUM(filled * price) AS cost, MAX(ts) AS last_ts
           FROM trades WHERE hive = 'kalshi' AND action = 'buy' AND filled > 0
           GROUP BY ticker, side, mode ORDER BY MAX(ts) DESC"""
    )
    book = await bus.latest("kalshi:book")
    live = {m["ticker"]: m for m in (book["data"]["markets"] if book else [])}
    client = KalshiClient(http)

    totals = {"cost": 0.0, "value": 0.0, "pnl": 0.0, "open": 0, "settled": 0, "wins": 0}
    rows = []
    for p in positions:
        contracts, cost = int(p["contracts"]), float(p["cost"])
        m = live.get(p["ticker"]) or await _market_info(client, p["ticker"]) or {}
        result = m.get("result")
        if result in ("yes", "no"):
            state = "won" if result == p["side"] else "lost"
            value = contracts * (1.0 if state == "won" else 0.0)
            totals["settled"] += 1
            totals["wins"] += state == "won"
        else:
            bid = m.get(f"{p['side']}_bid")
            state = "open" if bid is not None else "open (no bid)"
            value = contracts * (bid or 0.0)
            totals["open"] += 1
        rows.append({
            "ticker": p["ticker"],
            "side": p["side"],
            "mode": p["mode"],
            "contracts": contracts,
            "avg_price": round(cost / contracts, 4),
            "cost": round(cost, 2),
            "value": round(value, 2),
            "pnl": round(value - cost, 2),
            "state": state,
            "last_ts": p["last_ts"],
        })
        totals["cost"] += cost
        totals["value"] += value

    totals["pnl"] = totals["value"] - totals["cost"]
    totals = {k: round(v, 2) if isinstance(v, float) else v for k, v in totals.items()}

    trades = await db.fetch(
        "SELECT ts, ticker, side, count, filled, price, fair, status, mode FROM trades WHERE hive = 'kalshi' ORDER BY ts DESC LIMIT 25"
    )
    blocked = await bus.history("kalshi:blocked", 15)
    return {"totals": totals, "positions": rows, "trades": trades, "blocked": list(reversed(blocked))}
