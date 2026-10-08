from hives.kalshi.bots.risk import DEFAULT_LIMITS, RiskState, check

NOW = 1_000_000.0


def signal(**kw):
    return {"ts": NOW, "price": 0.40, "count": 1, "edge": 0.10, "ticker": "T", "side": "yes", **kw}


def state(**kw):
    return RiskState(**{"position": 0, "exposure": 0.0, "orders_last_hour": 0, "last_order_at": 0.0, **kw})


def test_good_signal_passes():
    assert check(signal(), state(), DEFAULT_LIMITS, NOW) is None


def test_blocks_each_limit():
    cases = [
        (signal(ts=NOW - 60), state(), "stale"),
        (signal(price=0.99), state(), "outside"),
        (signal(edge=0.01), state(), "edge"),
        (signal(), state(position=10), "contracts"),
        (signal(), state(exposure=99.9), "spend"),
        (signal(), state(orders_last_hour=20), "orders this hour"),
        (signal(), state(last_order_at=NOW - 10), "cooldown"),
        (signal(count=0), state(), "count"),
    ]
    for sig, st, words in cases:
        reason = check(sig, st, DEFAULT_LIMITS, NOW)
        assert reason and words in reason, (sig, st, reason)
