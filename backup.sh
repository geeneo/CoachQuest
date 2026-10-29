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

if [[ ${DATABASE_URL:-} == postgresql* ]]; then
  f="$BACKUPS/coachquest-pg-$stamp.sql.gz"
  # pipefail: a failed pg_dump fails the backup instead of leaving an empty file.
  if ! $DC exec -T db pg_dump -U "${POSTGRES_USER:-coachquest}" "${POSTGRES_DB:-coachquest}" | gzip > "$f"; then
    rm -f "$f"; echo "$(date '+%F %T') FAILED: pg_dump" >&2; exit 1
  fi
  pattern="coachquest-pg-*.sql.gz"
else
  f="$BACKUPS/coachquest-$stamp.db"
  sqlite3 "$DATA/coachquest.db" ".backup '$f'" 2>/dev/null || cp "$DATA/coachquest.db" "$f"
  gzip -f "$f"; f="$f.gz"
  pattern="coachquest-*.db.gz"
fi
ls -1t "$BACKUPS"/$pattern | tail -n +15 | xargs -r rm --
echo "$(date '+%F %T') Saved $f ($(du -h "$f" | cut -f1))"
