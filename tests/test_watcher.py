from datetime import UTC, datetime, timedelta

from hives.kalshi.bots.watcher import find_edges

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
CLOSE = (NOW + timedelta(hours=5)).isoformat().replace("+00:00", "Z")


def m(ticker, yes_ask=None, no_ask=None, close=CLOSE):
    return {"ticker": ticker, "yes_ask": yes_ask, "no_ask": no_ask, "close_time": close}


def test_finds_yes_and_no_edges_biggest_first():
    markets = [m("A", yes_ask=0.40), m("B", no_ask=0.20), m("C", yes_ask=0.70)]
    fair = {"A": {"fair": 0.55}, "B": {"fair": 0.60}, "C": {"fair": 0.65}}
    edges = find_edges(markets, fair, {"min_edge": 0.08}, NOW)
    assert [(e["ticker"], e["side"]) for e in edges] == [("B", "no"), ("A", "yes")]
    assert edges[0]["edge"] == 0.2


def test_skips_markets_about_to_close_and_extreme_prices():
    soon = (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    markets = [m("A", yes_ask=0.40, close=soon), m("B", yes_ask=0.02)]
    fair = {"A": {"fair": 0.9}, "B": {"fair": 0.9}}
    assert find_edges(markets, fair, {}, NOW) == []
