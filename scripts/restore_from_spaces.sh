#!/usr/bin/env bash
# Phase 8 — restore the DB from a Spaces backup. MANUAL trigger only.
#
#   ./scripts/restore_from_spaces.sh bfa-scout-2026-05-13-0300.sql.gz
#
# Lists available backups when run with no argument. This is a
# DESTRUCTIVE operation against DATABASE_URL — it drops & recreates
# the public schema before reloading. Guarded by an explicit typed
# confirmation. Never wired into cron.
set -euo pipefail

REPO_DIR="${BFA_SCOUT_DIR:-/home/bfa/bfa-scout}"
set -a; source "$REPO_DIR/.env.production"; set +a

export AWS_ACCESS_KEY_ID="$SPACES_KEY"
export AWS_SECRET_ACCESS_KEY="$SPACES_SECRET"

if [[ $# -lt 1 ]]; then
    echo "Available backups in s3://${SPACES_BUCKET}/backups/ :"
    aws s3 ls "s3://${SPACES_BUCKET}/backups/" \
        --endpoint-url "$SPACES_ENDPOINT"
    echo
    echo "Usage: $0 <backup-filename.sql.gz>"
    exit 0
fi

BACKUP_FILE="$1"
TMP="/tmp/${BACKUP_FILE}"

echo "!! DESTRUCTIVE RESTORE"
echo "!!   source : s3://${SPACES_BUCKET}/backups/${BACKUP_FILE}"
echo "!!   target : ${DATABASE_URL%%\?*}   (schema 'public' WILL be dropped)"
read -rp "Type EXACTLY 'restore ${BACKUP_FILE}' to proceed: " CONFIRM
if [[ "$CONFIRM" != "restore ${BACKUP_FILE}" ]]; then
    echo "Aborted (confirmation mismatch)."
    exit 1
fi

echo "==> Downloading"
aws s3 cp "s3://${SPACES_BUCKET}/backups/${BACKUP_FILE}" "$TMP" \
    --endpoint-url "$SPACES_ENDPOINT" --only-show-errors

echo "==> Dropping & recreating public schema"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
    -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "==> Restoring"
gunzip -c "$TMP" | psql "$DATABASE_URL" -v ON_ERROR_STOP=1

rm -f "$TMP"
echo "==> Restore complete. Restart the app:  ./scripts/deploy.sh"
