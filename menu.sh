#!/usr/bin/env bash
# Day-to-day server admin.
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a
DATA=${DATA_PATH:-./data}
BACKUPS=${BACKUP_PATH:-./backups}
DC="docker compose -p $COMPOSE_PROJECT -f docker-compose.yml"

while true; do
  cat <<MENU

CoachQuest ($COMPOSE_PROJECT) — commit on disk: $(git rev-parse --short HEAD)
 1) Version check (disk / remote / running)
 2) Deploy all        3) Deploy backend      4) Deploy frontend
 5) Logs: api         6) Logs: proxy
 7) Back up data (keeps last 14)
 8) Status            9) Docker cleanup (dangling images)
 q) Quit
MENU
  read -rp "> " choice
  case $choice in
    1) git fetch -q; echo "disk:    $(git rev-parse --short HEAD)"; echo "remote:  $(git rev-parse --short '@{u}')"
       echo "running: $(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$($DC ps -q api)" | grep ^BUILD_COMMIT= | cut -d= -f2)" ;;
    2) bash deploy.sh all ;;
    3) bash deploy.sh backend ;;
    4) bash deploy.sh frontend ;;
    5) $DC logs --tail 200 -f api ;;
    6) $DC logs --tail 200 -f proxy ;;
    7) mkdir -p "$BACKUPS"
       if [[ ${DATABASE_URL:-} == postgresql* ]]; then
         f="$BACKUPS/coachquest-pg-$(date +%Y%m%d-%H%M%S).sql.gz"
         $DC exec -T db pg_dump -U "${POSTGRES_USER:-coachquest}" "${POSTGRES_DB:-coachquest}" | gzip > "$f"
         ls -1t "$BACKUPS"/coachquest-pg-*.sql.gz | tail -n +15 | xargs -r rm --; echo "Saved $f"
       else
         f="$BACKUPS/coachquest-$(date +%Y%m%d-%H%M%S).db"
         sqlite3 "$DATA/coachquest.db" ".backup '$f'" 2>/dev/null || cp "$DATA/coachquest.db" "$f"
         gzip "$f"; ls -1t "$BACKUPS"/coachquest-*.db.gz | tail -n +15 | xargs -r rm --; echo "Saved $f.gz"
       fi ;;
    8) $DC ps ;;
    9) docker image prune -f ;;
    q) exit 0 ;;
  esac
done
