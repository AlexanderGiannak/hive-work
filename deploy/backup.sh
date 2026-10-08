#!/bin/sh
# Dumps Postgres once a day into ./backups and keeps the last $BACKUP_KEEP_DAYS.
# Restore one with:
#   gunzip -c backups/hive-YYYY-MM-DD.sql.gz | docker compose exec -T postgres psql -U hive hive
set -eu
export PGPASSWORD="$POSTGRES_PASSWORD"
KEEP="${BACKUP_KEEP_DAYS:-7}"

while true; do
  file="/backups/hive-$(date +%F).sql.gz"
  if pg_dump -h postgres -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$file.tmp"; then
    mv "$file.tmp" "$file"
    echo "backup: wrote $file ($(du -h "$file" | cut -f1))"
  else
    rm -f "$file.tmp"
    echo "backup: pg_dump FAILED" >&2
  fi
  ls -1t /backups/hive-*.sql.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
  sleep 86400
done
