#!/usr/bin/env bash
# First-time setup and image build. Run from the git checkout on the server.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Fill it in (secrets, PUBLIC_BASE_URL, keys) and run again."
  exit 1
fi
set -a; source .env; set +a

for v in PROXY_SHARED_SECRET TOKEN_ENCRYPTION_KEY PUBLIC_BASE_URL; do
  [[ -n "${!v:-}" ]] || { echo "Missing $v in .env"; exit 1; }
done

mkdir -p "${DATA_PATH:-./data}"
# The API container runs as uid 10001.
chown 10001 "${DATA_PATH:-./data}" 2>/dev/null || sudo chown 10001 "${DATA_PATH:-./data}" || true

COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo dev)
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TARGET=${1:-all}

if [[ $TARGET == all || $TARGET == backend ]]; then
  docker build -t "${APP_NAME}-api:latest" --build-arg BUILD_COMMIT="$COMMIT" --build-arg BUILD_TIME="$NOW" backend
fi
if [[ $TARGET == all || $TARGET == frontend ]]; then
  docker build -t "${APP_NAME}-proxy:latest" --build-arg BUILD_COMMIT="$COMMIT" -f nginx/Dockerfile .
fi
echo "Built ${APP_NAME} images at $COMMIT."
