#!/usr/bin/env bash
# Backup Postgres DB to local + optional S3-compatible target via rclone.
# Usage: BACKUP_DIR=/var/backups/apibank ./backup.sh
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/apibank}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
PG_HOST="${PG_HOST:-postgres}"
PG_USER="${PG_USER:-apibank}"
PG_DB="${PG_DB:-apibank}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"

mkdir -p "${BACKUP_DIR}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${BACKUP_DIR}/apibank-${TIMESTAMP}.sql.gz"

echo "creating dump ${ARCHIVE}"
PGPASSWORD="${PG_PASSWORD:?PG_PASSWORD env var required}" \
  pg_dump -h "${PG_HOST}" -U "${PG_USER}" -d "${PG_DB}" --no-owner --format=custom \
  | gzip -9 > "${ARCHIVE}"

if [[ -n "${RCLONE_REMOTE}" ]]; then
  echo "uploading to ${RCLONE_REMOTE}"
  rclone copy "${ARCHIVE}" "${RCLONE_REMOTE}" --quiet
fi

echo "pruning local backups older than ${RETENTION_DAYS} days"
find "${BACKUP_DIR}" -type f -name 'apibank-*.sql.gz' -mtime +"${RETENTION_DAYS}" -delete

echo "done"
