#!/usr/bin/env bash
# Back up the database (SQLite or Postgres, from DATABASE_URL) to BACKUP_PATH, keeping the last 14.
# Used by menu.sh (7, and the nightly job it can install with option 10).
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a
DATA=${DATA_PATH:-./data}
BACKUPS=${BACKUP_PATH:-./backups}
DC="docker compose -p $COMPOSE_PROJECT -f docker-compose.yml"
mkdir -p "$BACKUPS"
stamp=$(date +%Y%m%d-%H%M%S)
# What happened, for Admin → Storage (storage_watch.py reads it from the data folder).
status() {
  printf '%s\n' "at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$@" > "$DATA/backup-status.txt.tmp" 2>/dev/null &&
    chmod 644 "$DATA/backup-status.txt.tmp" && mv "$DATA/backup-status.txt.tmp" "$DATA/backup-status.txt" || true
}

if [[ ${DATABASE_URL:-} == postgresql* ]]; then
  f="$BACKUPS/coachquest-pg-$stamp.sql.gz"
  # pipefail: a failed pg_dump fails the backup instead of leaving an empty file.
  if ! $DC exec -T db pg_dump -U "${POSTGRES_USER:-coachquest}" "${POSTGRES_DB:-coachquest}" | gzip > "$f"; then
    rm -f "$f"; status "state=failed" "error=pg_dump failed"; echo "$(date '+%F %T') FAILED: pg_dump" >&2; exit 1
  fi
  pattern="coachquest-pg-*.sql.gz"
else
  f="$BACKUPS/coachquest-$stamp.db"
  if ! { sqlite3 "$DATA/coachquest.db" ".backup '$f'" 2>/dev/null || cp "$DATA/coachquest.db" "$f"; }; then
    rm -f "$f"; status "state=failed" "error=copying the SQLite database failed"; exit 1
  fi
  gzip -f "$f"; f="$f.gz"
  pattern="coachquest-*.db.gz"
fi
ls -1t "$BACKUPS"/$pattern | tail -n +15 | xargs -r rm --
status "state=ok" "file=$(basename "$f")" "size=$(stat -c %s "$f")"
echo "$(date '+%F %T') Saved $f ($(du -h "$f" | cut -f1))"
