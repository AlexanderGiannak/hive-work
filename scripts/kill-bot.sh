#!/usr/bin/env bash
# Kill one bot's process to prove the queen brings it back (the week 3 test).
#   scripts/kill-bot.sh kalshi Pricer
# Then watch: docker compose logs -f queen
set -euo pipefail
hive="${1:?usage: scripts/kill-bot.sh <hive> <BotClass>}"
bot="${2:?usage: scripts/kill-bot.sh <hive> <BotClass>}"
docker compose exec queen pkill -9 -f "core.runner $hive $bot" && echo "killed $hive/$bot, the queen should restart it within a few seconds"
