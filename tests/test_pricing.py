from datetime import UTC, datetime, timedelta

import pytest

from hives.kalshi.pricing import fair_value, prob_above, realized_vol

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def market(kind, floor=None, cap=None, hours=24):
    close = (NOW + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    return {"strike_type": kind, "floor": floor, "cap": cap, "close_time": close}


def test_at_the_money_is_about_a_coin_flip():
    assert prob_above(100, 100, 0.5, 1 / 365) == pytest.approx(0.5, abs=0.01)


def test_far_strikes_are_near_certain():
    assert prob_above(100, 50, 0.5, 1 / 365) > 0.99
    assert prob_above(100, 200, 0.5, 1 / 365) < 0.01


def test_expired_market_is_all_or_nothing():
    assert prob_above(101, 100, 0.5, 0) == 1.0
    assert prob_above(99, 100, 0.5, 0) == 0.0


def test_greater_less_and_between_add_up():
    above = fair_value(market("greater", floor=105), 100, 0.6, NOW)
    below = fair_value(market("less", cap=95), 100, 0.6, NOW)
    between = fair_value(market("between", floor=95, cap=105), 100, 0.6, NOW)
    assert above + below + between == pytest.approx(1.0, abs=1e-9)


def test_unknown_strike_type_is_skipped():
    assert fair_value(market("custom"), 100, 0.6, NOW) is None


def test_realized_vol_flat_prices_is_zero_and_short_history_is_none():
    assert realized_vol([100.0] * 20, 3600) == 0
    assert realized_vol([100.0, 101.0], 3600) is None
