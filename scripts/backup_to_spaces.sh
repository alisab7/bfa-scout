#!/usr/bin/env bash
# Phase 8 — daily pg_dump → DigitalOcean Spaces.
#
# Belt-and-braces over DO Managed Postgres's own automated backups
# (locked decision). Cron (droplet root or bfa user):
#
#   0 3 * * * /home/bfa/bfa-scout/scripts/backup_to_spaces.sh \
#       >> /var/log/bfa-backup.log 2>&1
#
# Reads DATABASE_URL + SPACES_* from .env.production. Uses the AWS CLI
# (s3-compatible; install once: `apt-get install -y awscli`) rather
# than s3cmd — fewer config files, native --endpoint-url support.
set -euo pipefail

REPO_DIR="${BFA_SCOUT_DIR:-/home/bfa/bfa-scout}"
set -a; source "$REPO_DIR/.env.production"; set +a

DATE="$(date +%Y-%m-%d-%H%M)"
BACKUP_FILE="bfa-scout-${DATE}.sql.gz"
TMP="/tmp/${BACKUP_FILE}"

echo "==> [$(date -Is)] pg_dump"
pg_dump "$DATABASE_URL" | gzip > "$TMP"
SIZE="$(du -h "$TMP" | cut -f1)"
echo "    dumped ${SIZE}"

echo "==> Uploading to s3://${SPACES_BUCKET}/backups/${BACKUP_FILE}"
AWS_ACCESS_KEY_ID="$SPACES_KEY" \
AWS_SECRET_ACCESS_KEY="$SPACES_SECRET" \
aws s3 cp "$TMP" "s3://${SPACES_BUCKET}/backups/${BACKUP_FILE}" \
    --endpoint-url "$SPACES_ENDPOINT" \
    --only-show-errors

echo "==> Cleanup"
rm -f "$TMP"

# Retention: list backup objects, delete anything older than 30 days.
# Conservative — only deletes within the backups/ prefix; never the
# bucket root (photos live at photos/).
echo "==> Pruning backups older than 30 days"
CUTOFF="$(date -d '30 days ago' +%Y-%m-%d)"
AWS_ACCESS_KEY_ID="$SPACES_KEY" \
AWS_SECRET_ACCESS_KEY="$SPACES_SECRET" \
aws s3 ls "s3://${SPACES_BUCKET}/backups/" \
    --endpoint-url "$SPACES_ENDPOINT" | while read -r line; do
    fdate="$(echo "$line" | awk '{print $1}')"
    fname="$(echo "$line" | awk '{print $4}')"
    [[ -z "$fname" ]] && continue
    if [[ "$fdate" < "$CUTOFF" ]]; then
        echo "    pruning $fname (dated $fdate)"
        AWS_ACCESS_KEY_ID="$SPACES_KEY" \
        AWS_SECRET_ACCESS_KEY="$SPACES_SECRET" \
        aws s3 rm "s3://${SPACES_BUCKET}/backups/${fname}" \
            --endpoint-url "$SPACES_ENDPOINT" --only-show-errors
    fi
done

echo "==> [$(date -Is)] Backup complete: ${BACKUP_FILE}"
