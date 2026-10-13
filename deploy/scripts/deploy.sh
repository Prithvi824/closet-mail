#!/usr/bin/env bash
# Deploy prebuilt images to the server: copy the compose file and env files, pull, migrate, start.
# The server never receives source code; CI publishes the images to GHCR on every push to main.
# Usage: deploy/scripts/deploy.sh [image-tag]   (default: the current commit, which CI tags by SHA)
# DEPLOY_HOST (user@host) comes from the environment or deploy/.env.
# Touches only ~/mail-alias and the "mailalias" compose project on the host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REMOTE_DIR="mail-alias"
HEALTH_TIMEOUT_SECONDS=90

for file in deploy/.env deploy/.env.prod; do
  [[ -f "$ROOT/$file" ]] || { echo "missing $file (see docs/runbook.md)" >&2; exit 1; }
done
HOST="${DEPLOY_HOST:-$(sed -n 's/^DEPLOY_HOST=//p' "$ROOT/deploy/.env" | tail -n 1)}"
[[ -n "$HOST" ]] || { echo "set DEPLOY_HOST=user@host in deploy/.env or the environment" >&2; exit 1; }
IMAGE_TAG="${1:-$(git -C "$ROOT" rev-parse HEAD)}"

# The host's .env is deploy/.env plus the image tag, so later manual `docker compose` runs
# on the host keep using the deployed version.
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
(umask 077 && { grep -v '^IMAGE_TAG=' "$ROOT/deploy/.env"; echo "IMAGE_TAG=$IMAGE_TAG"; } > "$STAGING/.env")

echo "== copy compose and env files to $HOST:~/$REMOTE_DIR (image tag $IMAGE_TAG)"
ssh "$HOST" "mkdir -p ~/$REMOTE_DIR/logs/api ~/$REMOTE_DIR/logs/processor ~/$REMOTE_DIR/logs/worker"
scp -q "$ROOT/deploy/docker-compose.yml" "$HOST:~/$REMOTE_DIR/docker-compose.yml"
scp -q "$STAGING/.env" "$HOST:~/$REMOTE_DIR/.env"
scp -q "$ROOT/deploy/.env.prod" "$HOST:~/$REMOTE_DIR/.env.prod"
ssh "$HOST" "chmod 600 ~/$REMOTE_DIR/.env ~/$REMOTE_DIR/.env.prod"

echo "== pull, migrate, start"
# `up` runs the one-shot migrate service first; the other backend services wait for it.
ssh "$HOST" "cd ~/$REMOTE_DIR && docker compose pull --quiet && docker compose up -d --remove-orphans"

echo "== wait for /healthz"
ssh "$HOST" "for i in \$(seq 1 $HEALTH_TIMEOUT_SECONDS); do
    if curl -fsS http://127.0.0.1:8080/healthz; then echo; exit 0; fi
    sleep 1
  done
  echo 'healthz did not become ready' >&2
  cd ~/$REMOTE_DIR && docker compose ps && docker compose logs --tail 40 api
  exit 1"
echo "== deployed $IMAGE_TAG"
