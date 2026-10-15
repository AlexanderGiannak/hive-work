#!/bin/bash
# Keeps the hive running on the Mac and up to date with GitHub. Cron runs it every 5 minutes:
#
#   */5 * * * * $HOME/hivework/scripts/update.sh >> $HOME/Library/Logs/hivework.log 2>&1
#
# Run it from the dedicated clone at ~/hivework, never your working copy: it resets
# the folder to origin/main. (It lives outside ~/Documents because macOS blocks cron
# from reading Documents, Desktop and Downloads.)
set -uo pipefail
export PATH="$HOME/.docker/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")/.." || exit 1

log() { echo "$(date '+%F %T') $*"; }

# One run at a time, since a rebuild can take longer than 5 minutes.
LOCK=/tmp/hivework-update.lock
if ! mkdir "$LOCK" 2>/dev/null; then
  [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30)" ] || exit 0
  log "removing stale lock"
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# Docker Desktop has to be running (it needs someone logged in to the Mac).
if ! docker info >/dev/null 2>&1; then
  log "Docker isn't running, starting Docker Desktop"
  open -a Docker
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 5; done
  docker info >/dev/null 2>&1 || { log "Docker still isn't up, will try again next run"; exit 1; }
fi

# Don't let the Mac sleep while it's plugged in. (Closing the lid still sleeps it.)
if ! pgrep -qf "caffeinate -s"; then
  nohup caffeinate -s >/dev/null 2>&1 &
  log "started caffeinate"
fi

# Pull new code from main.
build=""
if git fetch -q origin main; then
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    log "updating $(git rev-parse --short HEAD) -> $(git rev-parse --short origin/main)"
    git reset -q --hard origin/main
    build="--build"
  fi
else
  log "git fetch failed, keeping the current code"
fi

# Start anything that isn't running, and rebuild after an update. A no-op otherwise.
if out=$(docker compose --profile prod up -d $build --remove-orphans 2>&1); then
  [ -n "$build" ] && log "hive rebuilt and running"
  echo "$out" | grep -qE "Started|Recreated|Created" && [ -z "$build" ] && log "restarted stopped containers"
else
  log "docker compose failed:"
  echo "$out" | tail -5
  exit 1
fi
exit 0
