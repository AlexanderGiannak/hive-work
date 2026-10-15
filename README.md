# Hivework

A team of small bots that runs 24/7 on a Mac. Start with [build.md](build.md). It's the guide for the whole project. This file is the quick reference.

## Run it

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:8000. Within a minute you should see 8 bots alive, live BTC/ETH prices, Kalshi demo markets with fair values, and paper trades on the Kalshi page.

Useful commands:

```bash
docker compose logs -f queen               # all bot logs come through the queen
scripts/kill-bot.sh kalshi Pricer          # week 3 test: kill a bot, watch it come back
docker compose exec postgres psql -U hive  # poke at the database
docker compose down                        # stop (add -v to wipe the database too)
```

Run tests and lint without Docker:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest && ruff check .
```

## How it works

- **Queen** (`core/queen.py`) reads every `hives/*/hive.yml`, runs each bot in its own process, and restarts any that crash or stop sending heartbeats. A crash-looping bot waits longer between restarts and pings Discord.
- **Bots** (`core/bot.py`) post to and read from the **board**: Redis streams named `<hive>:<topic>` (`core/bus.py`).
- **Postgres** (`core/schema.sql`) keeps `records` (from the Recorder bot), `trades`, `errors`, `events` and `metrics`.
- **Dashboard** (`dashboard/`) has the overview with the overnight log at `/`, the Kalshi scoreboard at `/kalshi`, and a default page for every other hive at `/hive/<name>`.
- **Kill switch**: the button on the overview stops every bot until you turn it off. The Risk and Trader bots also refuse to trade while it's on.

### The Kalshi hive

```
CoinbaseFeed -> kalshi:crypto  \
KalshiBook   -> kalshi:book     > Pricer -> kalshi:fair -> Watcher -> kalshi:signals
StockFeed    -> kalshi:stocks  /
kalshi:signals -> Risk -> kalshi:orders -> Trader -> kalshi:fills
                       -> kalshi:blocked (with the reason)
```

- **Pricer** prices BTC/ETH "above $X at 5pm" markets with a simple lognormal model and volatility from hourly Coinbase candles (`hives/kalshi/pricing.py`). It's simple on purpose, so there's room to improve it.
- **Risk** limits are in `hive.yml`: contracts per market, dollars per 24h, orders per hour, and a cooldown per market.
- **Trader** paper trades unless you give it a Kalshi **demo** key. It refuses to talk to any non-demo Kalshi URL.
- Demo market prices often have nothing to do with real prices, so expect big "edges". That's fine. The point is that the whole pipeline works.

### Optional keys (all free)

| Key | What it turns on |
| --- | --- |
| `DISCORD_WEBHOOK_URL` | Alerts in #alerts (otherwise they print in the logs) |
| `FINNHUB_API_KEY` | StockFeed (finnhub.io free tier) |
| `KALSHI_KEY_ID` + `secrets/kalshi.pem` | Real orders on the Kalshi demo instead of paper trades. Make the key at demo.kalshi.co |

## Making your own hive (weeks 9 to 10)

```
hives/quakes/
  __init__.py
  hive.yml
  bots/__init__.py
  bots/quake_feed.py
```

```yaml
hive: quakes
bots:
  QuakeFeed: {}
  MagnitudeFilter: { min: 4.5 }
  DiscordAlert: { channel: alerts }   # shared bot: forwards quakes:alerts to Discord
  Recorder: { topics: [quakes] }      # shared bot: saves history to Postgres
```

Then add your hive to `HIVES` in `.env` (or leave `HIVES` empty to run every hive). `Recorder` and `DiscordAlert` live in `core/shared_bots.py`. Your page shows up at `/hive/quakes` automatically.

Bot tips:
- `await self.get_json(url)` handles 429s for you (backs off and retries).
- `await self.read("kalshi:book", max_age=60)` returns the latest data, or `None` if it's missing or stale.
- `async for data in self.listen("signals")` waits for new messages and heartbeats for you.
- Anything in your `hive.yml` entry ends up in `self.config`.

## The always-on hive (runs on a Mac)

```
Browser -> hive-work-dashboard.vercel.app        pages (dashboard/static)
             | /api/* rewrite
             v
           https://alexanders-macbook-pro.tail4e1a56.ts.net   Tailscale Funnel
             v
           localhost:8000 dashboard API -> Redis / Postgres <- queen + bots
```

The hive runs on a MacBook from a dedicated clone at `~/hivework` (not your working copy, and outside `~/Documents`, which macOS blocks cron from reading). Cron runs `scripts/update.sh` every 5 minutes. It starts Docker Desktop if needed, keeps the Mac awake while it's plugged in, pulls `main` from GitHub and rebuilds when there's new code, and restarts anything that stopped. Merging to `main` is the deploy.

Setting it up on a Mac:

1. Install Docker Desktop and Tailscale, sign in to both, and turn on Docker's "Start when you sign in".
2. `git clone https://github.com/AlexanderGiannak/hive-work.git ~/hivework`, then copy in `.env` and `secrets/kalshi.pem`.
3. `tailscale funnel --bg 8000` gives `localhost:8000` a public HTTPS address (the first time, it asks you to approve Funnel for the tailnet). Put that address in `dashboard/static/vercel.json`.
4. `crontab -e` and add:
   ```
   */5 * * * * $HOME/hivework/scripts/update.sh >> $HOME/Library/Logs/hivework.log 2>&1
   ```
5. Keep it plugged in, lid open, and logged in. If it sleeps, the hive pauses and comes back within 5 minutes of waking.

Logs: `tail -f ~/Library/Logs/hivework.log` for updates, `cat ~/Library/Logs/hivework.lastrun` for when cron last ran, `cd ~/hivework && docker compose logs -f queen` for the bots.

### Dashboard on Vercel

The pages are static files, so they're hosted on Vercel's free Hobby plan. `dashboard/static/vercel.json` forwards every `/api/*` call to the Mac through Tailscale Funnel.

1. In Vercel, import the GitHub repo. Set **Root Directory** to `dashboard/static`, **Framework** to Other, and leave the build command empty.
2. Vercel redeploys on every merge to `main`.
3. Pages load any time, but they only show data while the Mac is awake and online.

There's no login. Anyone with the link can see the dashboard **and press the kill switch**, so keep the link within the team.
