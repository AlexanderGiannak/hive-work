"""Runs a single bot. The queen starts one of these per bot:

    python -m core.runner kalshi CoinbaseFeed

You can run it yourself too, to test one bot without the queen.
"""

import asyncio
import logging
import os
import signal
import sys

from core.hive import find_bot_class, load_hive


def setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def main(hive_name: str, cls_name: str) -> None:
    hive = load_hive(hive_name)
    spec = next((b for b in hive.bots if b.cls_name == cls_name), None)
    config = spec.config if spec else {}
    bot = find_bot_class(hive_name, cls_name)(hive_name, config)

    task = asyncio.create_task(bot.run())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        bot.log.info("stopped")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m core.runner <hive> <BotClass>")
    setup_logging()
    asyncio.run(main(sys.argv[1], sys.argv[2]))
