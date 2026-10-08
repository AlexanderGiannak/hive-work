# Hivework

A team of small bots that runs 24/7 on a free server. Start with [build.md](build.md). It's the guide for the whole project. This file is the quick reference.

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

## Server (whoever runs it)

```
Browser -> <project>.vercel.app          dashboard pages (dashboard/static)
             | /api/* rewrite
             v
           https://hivework.duckdns.org  Caddy, HTTPS only
             v
           dashboard API -> Redis / Postgres <- queen + bots
```

1. Oracle Cloud Always Free Ubuntu ARM VM. Open ports 80/443 in the VCN security list.
2. Claim `hivework` at duckdns.org and point it at the server's public IP (the DuckDNS container keeps it updated).
3. `deploy/server-setup.sh` installs Docker, opens the firewall, adds swap and clones the repo.
4. `cp .env.example .env` and fill in the server-only section (DuckDNS token, Discord). Copy `secrets/kalshi.pem` over by hand.
5. `docker compose --profile prod up -d --build` adds Caddy (HTTPS for `hivework.duckdns.org`), the DuckDNS updater and daily backups to `./backups`.
6. Auto deploys: set repo variable `DEPLOY_ENABLED=true` and secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`. After CI passes on `main`, `.github/workflows/deploy.yml` updates the server.

### Dashboard on Vercel

The pages are static files, so they're hosted on Vercel's free Hobby plan. `dashboard/static/vercel.json` forwards every `/api/*` call to `https://hivework.duckdns.org`. If you use a different DuckDNS name, change it there and in `.env`.

1. In Vercel, import the GitHub repo. Set **Root Directory** to `dashboard/static`, **Framework** to Other, and leave the build command empty. (Or run `npx vercel` inside `dashboard/static`.)
2. Vercel redeploys on every merge to `main`. The site is at `<project>.vercel.app`; Vercel picks another name if `hivework` is taken.
3. Pages load right away, but they only show data once the server is up at `hivework.duckdns.org`.

There's no login. Anyone with the link can see the dashboard **and press the kill switch**, so keep the link within the team.
