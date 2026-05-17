#!/usr/bin/env bash
# Restore Postgres DB from a pg_dump custom-format gzipped archive.
# Usage: ./restore.sh /var/backups/apibank/apibank-20260516T100000Z.sql.gz
set -euo pipefail

ARCHIVE="${1:?archive path required}"
PG_HOST="${PG_HOST:-postgres}"
PG_USER="${PG_USER:-apibank}"
PG_DB="${PG_DB:-apibank}"

echo "restoring ${ARCHIVE} into ${PG_DB}@${PG_HOST}"
gunzip -c "${ARCHIVE}" | PGPASSWORD="${PG_PASSWORD:?PG_PASSWORD required}" \
  pg_restore -h "${PG_HOST}" -U "${PG_USER}" -d "${PG_DB}" --clean --if-exists --no-owner

echo "done"
