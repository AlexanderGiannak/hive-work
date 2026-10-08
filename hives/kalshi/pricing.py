"""Fair value math for Kalshi price markets.

We treat the price as a random walk in log space (lognormal, no drift) and ask
"what's the chance it ends above/below/between the strike(s) at close?"
This ignores a lot (fat tails, the 60-second settlement average, fees), which
makes it a fine starting point and a good thing to improve.
"""

import math
from datetime import UTC, datetime

SECONDS_PER_YEAR = 365 * 24 * 3600


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def prob_above(spot: float, strike: float, vol: float, years: float) -> float:
    """P(price at close > strike)."""
    if years <= 0 or vol <= 0:
        return 1.0 if spot > strike else 0.0
    sd = vol * math.sqrt(years)
    d2 = (math.log(spot / strike) - 0.5 * sd * sd) / sd
    return norm_cdf(d2)


def fair_value(market: dict, spot: float, vol: float, now: datetime | None = None) -> float | None:
    """Fair YES price for a market summary (see kalshi_api.summarize_market), or None if we can't price it."""
    now = now or datetime.now(UTC)
    close = datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
    years = (close - now).total_seconds() / SECONDS_PER_YEAR
    kind, floor, cap = market.get("strike_type"), market.get("floor"), market.get("cap")

    if kind in ("greater", "greater_or_equal") and floor:
        p = prob_above(spot, floor, vol, years)
    elif kind in ("less", "less_or_equal") and cap:
        p = 1 - prob_above(spot, cap, vol, years)
    elif kind == "between" and floor and cap:
        p = prob_above(spot, floor, vol, years) - prob_above(spot, cap, vol, years)
    else:
        return None
    return min(max(p, 0.0), 1.0)


def realized_vol(closes: list[float], seconds_per_bar: float) -> float | None:
    """Annualized volatility from a list of closing prices, oldest first."""
    if len(closes) < 10:
        return None
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False) if a > 0 and b > 0]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * SECONDS_PER_YEAR / seconds_per_bar)
