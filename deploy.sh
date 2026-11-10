#!/usr/bin/env bash
# Pull, rebuild and restart. Usage: bash deploy.sh [all|backend|frontend]
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a
TARGET=${1:-all}

# Only a commit whose GitHub checks passed goes live. FORCE=1 deploys anyway (an emergency, or no
# GITHUB_TOKEN for a private repository): say why in the deploy log.
git fetch -q origin
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo origin/main)
sha=$(git rev-parse "$upstream")
ci=$(bash scripts/ci-status.sh "$sha")
echo "GitHub checks for ${sha:0:7}: $ci"
if [[ $ci != success && ${FORCE:-0} != 1 ]]; then
  echo "Not deployed: the checks for this commit are '$ci'. Fix them (or wait for them), or run with FORCE=1." >&2
  exit 3
fi
git merge --ff-only "$upstream"
bash build.sh "$TARGET"

case $TARGET in
  backend) SERVICES=api ;;
  frontend) SERVICES=proxy ;;
  *) SERVICES="api proxy" ;;
esac
# On Postgres (docs/postgres.md), make sure the database container runs too.
if [[ ${DATABASE_URL:-} == postgresql* && $TARGET != frontend ]]; then
  SERVICES="db $SERVICES"
fi
# Same project name Portainer uses, or you get a second, disconnected stack.
docker compose -p "$COMPOSE_PROJECT" -f docker-compose.yml up -d --no-deps $SERVICES
docker compose -p "$COMPOSE_PROJECT" -f docker-compose.yml ps
