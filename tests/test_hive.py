from core.bot import Bot, snake_case
from core.hive import available_hives, find_bot_class, load_hive


def test_every_hive_loads_and_every_bot_class_exists():
    hives = available_hives()
    assert "kalshi" in hives
    for name in hives:
        hive = load_hive(name)
        assert hive.bots, f"{name} has no bots"
        for spec in hive.bots:
            cls = find_bot_class(name, spec.cls_name)
            bot = cls(name, spec.config)
            assert bot.every >= 0


def test_topics_are_prefixed_with_the_hive():
    class QuakeFeed(Bot):
        async def run_once(self):
            pass

    bot = QuakeFeed("quakes", {"every": 30})
    assert bot.name == "quake_feed"
    assert bot.every == 30
    assert bot.topic("quakes") == "quakes:quakes"
    assert bot.topic("kalshi:book") == "kalshi:book"


def test_snake_case():
    assert snake_case("CoinbaseFeed") == "coinbase_feed"
    assert snake_case("Pricer") == "pricer"

