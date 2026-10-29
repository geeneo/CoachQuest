#!/usr/bin/env bash
# Pull, rebuild and restart. Usage: bash deploy.sh [all|backend|frontend]
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a
TARGET=${1:-all}

git pull --ff-only
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
