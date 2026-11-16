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
# Colour only on a terminal, and never with NO_COLOR set.
if [[ -t 1 && -z ${NO_COLOR:-} ]]; then
  B=$'\e[1m' D=$'\e[2m' G=$'\e[32m' Y=$'\e[33m' R=$'\e[31m' C=$'\e[36m' X=$'\e[0m'
else
  B= D= G= Y= R= C= X=
fi
on()  { printf '%s● ON %s' "$G" "$X"; }
off() { printf '%s○ OFF%s' "$Y" "$X"; }
nightly_status() {
  if nightly_installed; then
    last=$(ls -1t "$BACKUPS"/coachquest-*.gz 2>/dev/null | head -1 || true)
    if [[ -n $last ]]; then
      printf '%s  last %s  %s(choose to remove)%s' "$(on)" "$(date -r "$last" '+%d %b %H:%M')" "$D" "$X"
    else
      printf '%s  no backup yet  %s(choose to remove)%s' "$(on)" "$D" "$X"
    fi
  else
    printf '%s  %s(choose to install)%s' "$(off)" "$D" "$X"
  fi
}
agent_status() {
  if agent_installed; then printf '%s  %s(choose to remove)%s' "$(on)" "$D" "$X"
  else printf '%s  %s(choose to install)%s' "$(off)" "$D" "$X"; fi
}
running_commit() {
  local id; id=$($DC ps -q api 2>/dev/null || true)
  [[ -n $id ]] || return 0
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$id" 2>/dev/null | grep ^BUILD_COMMIT= | cut -d= -f2 || true
}
# One summary line: what's on disk, what's running, what's up, and whether GitHub had more at the last fetch.
header() {
  local disk running up all behind line
  disk=$(git rev-parse --short HEAD)
  running=$(running_commit)
  up=$($DC ps -q --status running 2>/dev/null | wc -l)
  all=$($DC ps -aq 2>/dev/null | wc -l)
  behind=$(git rev-list --count HEAD..@{u} 2>/dev/null || echo 0)
  line="${C}════════════════════════════════════════════════════════════${X}"
  echo; echo "$line"
  printf ' %sCoachQuest%s · %s    disk %s%s%s' "$B" "$X" "$COMPOSE_PROJECT" "$B" "$disk" "$X"
  if [[ -z $running ]]; then printf '   running %snot running%s' "$R" "$X"
  elif [[ $disk == "$running"* || $running == "$disk"* ]]; then printf '   running %s%s ✓%s' "$G" "${running:0:7}" "$X"
  else printf '   running %s%s (deploy to update)%s' "$Y" "${running:0:7}" "$X"; fi
  echo
  if (( all > 0 && up == all )); then printf ' containers %s%s/%s up%s' "$G" "$up" "$all" "$X"
  else printf ' containers %s%s/%s up%s' "$R" "$up" "$all" "$X"; fi
  (( behind > 0 )) && printf '   %s%s new on GitHub (at last check)%s' "$Y" "$behind" "$X"
  echo; echo "$line"
}
section() { printf ' %s%s%s\n' "$D" "$1" "$X"; }

# Ctrl+C stops what an option is doing (e.g. following logs) and comes back to the menu.
trap 'echo' INT

while true; do
  header
  section DEPLOY
  echo "   1) Version check (disk / remote / running)"
  echo "   2) Deploy all        3) Deploy backend      4) Deploy frontend"
  section MONITOR
  echo "   5) Logs: api         6) Logs: proxy         8) Status"
  section MAINTENANCE
  echo "   7) Back up data now (keeps last 14)"
  echo "   9) Docker cleanup (dangling images)"
  section AUTOMATION
  printf '  10) Nightly backup 02:17       %s\n' "$(nightly_status)"
  printf '  11) Updates from Admin page    %s\n' "$(agent_status)"
  echo "   q) Quit"
  read -rp "> " choice
  [[ $choice == [qQ] ]] && exit 0
  [[ -z $choice ]] && continue
  echo
  # Each option runs in a subshell: a failing command reports here instead of closing the menu.
  set +e
  (
  case $choice in
    1) git fetch -q; echo "disk:    $(git rev-parse --short HEAD)"; echo "remote:  $(git rev-parse --short '@{u}')"
       echo "running: $(running_commit)" ;;
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
    *) echo "${Y}No option \"$choice\" - pick a number from the list.${X}"; exit 0 ;;
  esac
  )
  rc=$?
  set -e
  if (( rc == 130 )); then echo "${D}Stopped.${X}"
  elif (( rc != 0 )); then echo "${R}✗ Option $choice failed (exit $rc) - see the output above.${X}"; fi
done
