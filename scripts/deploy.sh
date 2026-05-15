#!/usr/bin/env bash
# Phase 8 — on-droplet deploy / redeploy.
#
#   ssh bfa@<droplet>
#   cd /home/bfa/bfa-scout && ./scripts/deploy.sh
#
# Idempotent: safe to re-run. Pulls master, rebuilds the image,
# recreates the stack, and gates on /healthz before declaring success.
set -euo pipefail

REPO_DIR="${BFA_SCOUT_DIR:-/home/bfa/bfa-scout}"
COMPOSE="docker compose -f docker-compose.prod.yml"

cd "$REPO_DIR"

echo "==> [1/6] Pulling latest master"
git pull origin master

echo "==> [2/6] Sanity: required files present"
for f in .env.production nginx/certs/origin.crt nginx/certs/origin.key; do
    if [[ ! -f "$f" ]]; then
        echo "    MISSING: $f — see DEPLOY.md 'First deploy'." >&2
        exit 1
    fi
done

echo "==> [3/6] Building image"
$COMPOSE build

echo "==> [4/6] Recreating stack"
$COMPOSE up -d

echo "==> [5/6] Waiting for app healthcheck (max 90s)"
deadline=$(( SECONDS + 90 ))
until curl -fsS -k https://localhost/healthz >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
        echo "    Healthcheck did not pass within 90s." >&2
        echo "    Recent app logs:" >&2
        $COMPOSE logs --tail=50 app >&2
        exit 1
    fi
    sleep 3
done

echo "==> [6/6] Healthcheck OK"
$COMPOSE ps
echo "==> Deploy complete."
