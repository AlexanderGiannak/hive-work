"""Bots any hive can list in its hive.yml without writing them.

    bots:
      Recorder: { topics: [prices, alerts], every: 60 }
      DiscordAlert: { channel: alerts }
"""

from core import bus, db
from core.bot import Bot


class Recorder(Bot):
    """Copies the latest message on each topic into Postgres every `every` seconds.

    Sampling (instead of saving every message) keeps the database small enough
    for the free server. Skips a topic if nothing new arrived since last time.
    """

    every = 60

    async def setup(self) -> None:
        self.topics = [self.topic(t) for t in self.config.get("topics", [])]
        self.seen: dict[str, float] = {}
        if not self.topics:
            self.log.warning("no topics configured, nothing to record")

    async def run_once(self) -> None:
        saved = 0
        for topic in self.topics:
            msg = await bus.latest(topic)
            if msg is None or msg["ts"] <= self.seen.get(topic, 0):
                continue
            await db.record(topic, msg["data"])
            self.seen[topic] = msg["ts"]
            saved += 1
        self.log.debug("recorded %d topics", saved)


class DiscordAlert(Bot):
    """Forwards every message on a topic (default `<hive>:alerts`) to Discord.

    Publish either a string or a dict with a "message" key to that topic.
    """

    every = 0

    async def run_once(self) -> None:
        source = self.config.get("topic", "alerts")
        channel = self.config.get("channel", "alerts")
        async for data in self.listen(source):
            text = data.get("message") if isinstance(data, dict) else str(data)
            if text:
                await self.alert(text, channel)
