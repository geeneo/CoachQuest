#!/usr/bin/env bash
# Day-to-day server admin.
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a
DATA=${DATA_PATH:-./data}
BACKUPS=${BACKUP_PATH:-./backups}
DC="docker compose -p $COMPOSE_PROJECT -f docker-compose.yml"
# Marks this folder's nightly backup line in root's crontab (option 10).
CRON_TAG="# coachquest-backup:$PWD"
nightly_installed() { crontab -l 2>/dev/null | grep -qF "$CRON_TAG"; }
# Option 11: the deploy agent (deploy-agent.sh) runs each minute and carries out updates asked for on
# the admin page. The web app only leaves a request file; it never gets Docker or root.
AGENT_TAG="# coachquest-deploy-agent:$PWD"
agent_installed() { crontab -l 2>/dev/null | grep -qF "$AGENT_TAG"; }
agent_status() { agent_installed && echo "ON - choose to remove" || echo "OFF - choose to install"; }
nightly_status() {
  if nightly_installed; then
    last=$(ls -1t "$BACKUPS"/coachquest-*.gz 2>/dev/null | head -1)
    echo "ON (last: $([[ -n $last ]] && basename "$last" || echo "none yet")) - choose to remove"
  else
    echo "OFF - choose to install"
  fi
}

while true; do
  cat <<MENU

CoachQuest ($COMPOSE_PROJECT) — commit on disk: $(git rev-parse --short HEAD)
 1) Version check (disk / remote / running)
 2) Deploy all        3) Deploy backend      4) Deploy frontend
 5) Logs: api         6) Logs: proxy
 7) Back up data now (keeps last 14)
 8) Status            9) Docker cleanup (dangling images)
10) Nightly backup at 02:17: $(nightly_status)
11) Updates from Admin → Update CoachQuest: $(agent_status)
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
    7) bash backup.sh ;;
    8) $DC ps ;;
    11) if ! command -v crontab >/dev/null; then
          echo "cron isn't installed: dnf install -y cronie && systemctl enable --now crond (apt: cron)"
        elif agent_installed; then
          read -rp "Stop updates from the admin page? [y/N] " yn
          if [[ $yn == [yY] ]]; then
            { crontab -l 2>/dev/null | grep -vF "$AGENT_TAG" || true; } | crontab -
            echo "Removed. Deploy here with option 2 as before."
          fi
        else
          { crontab -l 2>/dev/null || true; echo "* * * * * cd $PWD && bash deploy-agent.sh $AGENT_TAG"; } | crontab -
          bash deploy-agent.sh
          echo "Installed: super admins can now check for and deploy updates under Admin → Update CoachQuest."
        fi ;;
    10) if ! command -v crontab >/dev/null; then
          echo "cron isn't installed: dnf install -y cronie && systemctl enable --now crond (apt: cron)"
        elif nightly_installed; then
          read -rp "Remove the nightly backup? [y/N] " yn
          if [[ $yn == [yY] ]]; then
            { crontab -l 2>/dev/null | grep -vF "$CRON_TAG" || true; } | crontab -
            echo "Removed. Backups already made stay in $BACKUPS."
          fi
        else
          mkdir -p "$BACKUPS"
          { crontab -l 2>/dev/null || true; echo "17 2 * * * cd $PWD && bash backup.sh >> $BACKUPS/backup.log 2>&1 $CRON_TAG"; } | crontab -
          echo "Installed: every night at 02:17 (server time), log in $BACKUPS/backup.log. Making one now to test:"
          bash backup.sh
        fi ;;
    9) docker image prune -f ;;
    q) exit 0 ;;
  esac
done
