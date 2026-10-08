# Hivework: Build Guide

Hey everyone, welcome to Hivework. This is the doc to start from. Read the whole thing once, then keep it open while you work.

## What we're building

A team of small bots that runs 24/7 on a free server. Each bot does one job. They don't talk to each other directly, they post to a shared board (Redis), and a dashboard shows what the whole team did while we were asleep.

The first hive watches Kalshi's demo market next to live crypto and stock prices and makes trades with fake money. In weeks 9 and 10, each of you builds your own hive on the same system to track whatever you want.

Everything we use is free. Nobody should ever pay for anything on this project. If something asks for a credit card, stop and ask me first.

## How it fits together

```
You (browser)
   |
 Caddy  (HTTPS + login)
   |
Dashboard  <----  Redis board  <---->  Bots
   |                  |
Postgres  <-------- Queen  (starts bots, restarts dead ones)
```

- **Queen** reads a `hive.yml`, starts every bot in it, and restarts any bot that stops checking in.
- **Redis board** is where bots post data and read it. Topics look like `kalshi:prices`.
- **Postgres** keeps the history: prices, trades, errors, metrics.
- **Dashboard** is a FastAPI app that shows it all live.
- **Bots** are small Python classes. Feed bots pull data, brain bots analyze it, action bots do something with it.

## The stack

| Piece | What we use |
| --- | --- |
| Server | Oracle Cloud Always Free (2 ARM cores, 12 GB RAM, Ubuntu) |
| Containers | Docker + Docker Compose |
| Language | Python 3.12 |
| Message board | Redis |
| Database | Postgres |
| Dashboard | FastAPI + plain HTML/JS |
| Domain + HTTPS | DuckDNS + Caddy |
| Code + deploys | GitHub + GitHub Actions |
| Alerts | Discord webhook |

## Setup on your laptop (do this before our first meeting)

1. Make a GitHub account if you don't have one, and send me your username so I can add you to the repo.
2. Install:
   - [Git](https://git-scm.com/downloads)
   - [VS Code](https://code.visualstudio.com/)
   - [Python 3.12](https://www.python.org/downloads/)
   - [Docker Desktop](https://www.docker.com/products/docker-desktop/) (lets you run the whole hive on your own laptop)
3. Join the Hivework Discord and turn on notifications for #alerts.
4. Clone the repo once I add you:

```bash
git clone https://github.com/AlexanderGiannak/hive-work.git
cd hive-work
```

5. Copy the example env file. Your local copy uses local Redis and Postgres, no real keys needed:

```bash
cp .env.example .env
```

6. Start everything locally:

```bash
docker compose up --build
```

If you see the queen logging heartbeats, you're good.

You don't need access to the real server. I handle that. Your code gets to the server through pull requests, and the server updates itself when I merge.

## Repo layout

```
hivework/
  docker-compose.yml
  Dockerfile
  .env.example        copy this to .env, never commit .env
  core/
    bot.py            the Bot class every bot uses
    queen.py          starts and watches bots
    bus.py            Redis helpers
    db.py             Postgres helpers
    alerts.py         Discord messages
  dashboard/
    app.py
    static/
  hives/
    kalshi/
      hive.yml
      bots/
```

The rule: `core/` is shared and changes slowly. Your hive lives in its own folder under `hives/` and shouldn't touch anyone else's.

## Writing a bot

Every bot looks about like this:

```python
from core.bot import Bot

class QuakeFeed(Bot):
    name = "quake_feed"
    every = 60  # seconds between runs

    async def run_once(self):
        quakes = await get_usgs_quakes()   # your code
        await self.publish("quakes", quakes)
```

- `run_once` is your bot's job.
- `publish` posts to the board under your hive's name, like `quakes:quakes`.
- The base class handles heartbeats and errors for you. If your bot runs nonstop (like a WebSocket feed), call `self.heartbeat()` inside your loop every few seconds.

Then add it to your hive's `hive.yml`:

```yaml
hive: quakes
bots:
  QuakeFeed: {}
  MagnitudeFilter: { min: 4.5 }
  DiscordAlert: { channel: alerts }
```

## How we work

1. Pick an issue from the GitHub project board and assign yourself.
2. Make a branch: `git checkout -b yourname/short-description`
3. Commit small and often.
4. Open a pull request. Say what it does and how you tested it.
5. Someone reviews it, then I merge. The server deploys itself.

Nobody edits files directly on the server. Ever.

## Tracks

Everyone works on the core together in weeks 1 to 8, but each of you owns one track.

| Track | What you own |
| --- | --- |
| Queen | Starting bots from hive.yml, heartbeats, restarts, the kill switch |
| Bots | The Bot class and the Kalshi hive bots (feeds, pricer, watcher, risk, trader) |
| Board + database | Redis topics, Postgres tables, the Recorder bot |
| Dashboard | Live status page, Kalshi scoreboard, overnight log |
| Infra + safety | Docker, deploys, Discord alerts, backups, rate limits |

## Schedule

| Week | Goal | Done when |
| --- | --- | --- |
| 1 | Accounts, laptop setup, server up | Everyone runs the hive locally |
| 2 | Docker, Redis, Postgres, repo layout | `docker compose up` starts everything |
| 3 | Bot class, queen, heartbeats, alerts | A bot gets killed and comes back by itself |
| 4 | Dashboard v1, domain, HTTPS | Live bot status at our link |
| 5 | Coinbase and stock feed bots | Prices stream in all night |
| 6 | Kalshi order book + pricer | Fair values show next to Kalshi prices |
| 7 | Watcher, risk, trader on demo | First demo trades, risk blocks a bad one |
| 8 | Recorder, scoreboard, backups, auto deploys | Hive runs a full weekend untouched |
| 9 | Start your own hive | Your first bot is posting data |
| 10 | Polish + demo day | Your hive ran 48 hours straight |

## Week 1 to-do

- [ ] Laptop setup above, all the way through `docker compose up`
- [ ] Send me your GitHub username
- [ ] Join Discord
- [ ] Read through `core/bot.py` and `core/queen.py`, even if they're just stubs
- [ ] Look through the hive list below and start thinking about what you'd want to track

## Pick your own hive (weeks 9 to 10)

Anything that changes over time and has a free API works. Some ideas:

**Markets and trading**
- Your own Kalshi demo strategy, racing the team hive
- Crypto price alerts from the Coinbase public feed
- Stock or ETF tracker using a free stock data API

**Weather and nature**
- NOAA / National Weather Service: overnight forecast tracker that checks how accurate yesterday's forecast was
- National Hurricane Center: storm tracker that alerts when something is heading toward Tampa Bay
- USGS earthquakes: live quake feed with alerts over a certain magnitude
- NOAA tides and buoys: ocean conditions for fishing, surfing or boating
- Air quality (AirNow, OpenAQ): pollution alerts by city

**Space**
- ISS location: logs where the space station is and alerts when it's passing overhead
- NASA asteroid feed: near-Earth asteroids flying by this week
- NASA space weather: solar flares and geomagnetic storms (when you might see auroras)
- NASA FIRMS: satellite-detected wildfires around the world

**Sky and travel**
- OpenSky Network: live flight tracking, like counting planes over Tampa every hour
- Real-time transit feeds: bus delays, if your city publishes them

**Tech and the internet**
- GitHub: trending repos or new releases from tools you use
- Hacker News: what blew up in tech overnight, summarized by morning
- Wikipedia live edits stream: spikes often mean breaking news
- NVD security vulnerabilities: new CVEs for software your projects use
- Website uptime: ping sites and alert when one goes down

**Economy and public data**
- FRED: unemployment, inflation and other indicators
- EIA: weekly gas and energy prices
- USAJOBS: new federal internships or jobs matching keywords
- openFDA: new food and drug recalls

**Games and fun**
- Steam: player counts for games over time
- Sports APIs: live scores and stats (check the free tier first)
- Internship radar: ping Discord when new internships drop

Your hive is done when it has a feed bot, a brain bot, an alert bot, a page on the dashboard, and it ran 48 hours with nobody touching it.

## Rules

1. Check each API's terms and rate limits before building on it. Official APIs only, no scraping sites that say not to.
2. Don't build bots that track specific private people. Public data about the world is fair game.
3. Fake money only. Anything that trades runs on the Kalshi demo.
4. No keys or passwords in code or commits. They go in `.env`, which is already in `.gitignore`.
5. Every bot sends heartbeats, or the queen keeps restarting it.
6. Topic names start with your hive name.
7. If an API returns a 429, slow down and retry later.
8. Keep your hive under about 1 GB of RAM. Ask before adding anything heavy.
9. Every change goes through a pull request.

## Stuck?

Post in #help on Discord with what you tried, what you expected, and the error. Screenshots of the full error help a lot. Nobody gets judged for asking, this is how we all learn.

Let's build it.

Jake
