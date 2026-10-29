#!/usr/bin/env bash
# Carries out what a super admin asks for on Admin → Update CoachQuest. Runs every minute from
# root's crontab (menu.sh option 11 installs or removes it).
#
# The web app never gets Docker or root: it only drops a request file in DATA_PATH/deploy
# (kind=check or kind=deploy, target=all|backend|frontend). This script, on the server, reads it,
# runs the normal deploy.sh, and writes back what happened:
#   agent.txt     when it last ran (the admin page shows whether the agent is alive)
#   versions.txt  the commit on disk, the newest on GitHub, and the commits in between
#   status.txt    the current or last deploy: state, target, who, when, result
#   deploy.log    the output of the last deploy
#   history.log   one line per deploy
set -uo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a
DIR="${DATA_PATH:-./data}/deploy"
mkdir -p "$DIR"
chown 10001 "$DIR" 2>/dev/null || true  # the API container's user writes requests here
exec 9>"$DIR/.lock"
flock -n 9 || exit 0  # a deploy from the previous minute is still running

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
field() { grep -m1 "^$1=" "$2" 2>/dev/null | cut -d= -f2- | tr -cd '[:alnum:]@._+:-'; }
write() {  # write file atomically, readable by the API
  local f=$1; shift
  printf '%s\n' "$@" > "$f.tmp" && chmod 644 "$f.tmp" && mv "$f.tmp" "$f"
}

versions() {
  git fetch -q origin 2>/dev/null
  local upstream
  upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo origin/main)
  {
    echo "checked=$(now)"
    echo "branch=$(git rev-parse --abbrev-ref HEAD)"
    echo "disk=$(git rev-parse --short HEAD)"
    echo "remote=$(git rev-parse --short "$upstream" 2>/dev/null)"
    echo "dirty=$(git status --porcelain --untracked-files=no | wc -l)"
    echo "--- commits"
    git log --format='%h%x09%ad%x09%s' --date=short "HEAD..$upstream" 2>/dev/null | head -50
  } > "$DIR/versions.txt.tmp" && chmod 644 "$DIR/versions.txt.tmp" && mv "$DIR/versions.txt.tmp" "$DIR/versions.txt"
}

write "$DIR/agent.txt" "seen=$(now)"

REQ="$DIR/request.txt"
if [[ -f $REQ ]]; then
  kind=$(field kind "$REQ")
  target=$(field target "$REQ")
  by=$(field by "$REQ")
  rm -f "$REQ"
  case $kind in
    check) versions ;;
    deploy)
      case $target in all | backend | frontend) ;; *) target=all ;; esac
      before=$(git rev-parse --short HEAD)
      started=$(now)
      write "$DIR/status.txt" "state=running" "target=$target" "by=$by" "started=$started" "before=$before"
      bash deploy.sh "$target" > "$DIR/deploy.log" 2>&1
      rc=$?
      chmod 644 "$DIR/deploy.log"
      after=$(git rev-parse --short HEAD)
      state=$([[ $rc == 0 ]] && echo done || echo failed)
      write "$DIR/status.txt" "state=$state" "target=$target" "by=$by" "started=$started" \
        "finished=$(now)" "before=$before" "after=$after" "exit=$rc"
      echo "$started $state $target $before→$after by $by" >> "$DIR/history.log"
      chmod 644 "$DIR/history.log"
      versions
      ;;
  esac
elif [[ ! -f $DIR/versions.txt ]] || [[ -n $(find "$DIR/versions.txt" -mmin +30) ]]; then
  versions  # look for new commits every 30 minutes
fi
