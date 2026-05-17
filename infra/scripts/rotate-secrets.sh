#!/usr/bin/env bash
# Helper to rotate APIBANK_FERNET_KEYS. Place new key first; keep old keys for 7 days.
# Run: ./rotate-secrets.sh new-name <new-fernet-key>
set -euo pipefail

NAME="${1:?name required}"
NEW_KEY="${2:?new key required}"

ENV_FILE="${ENV_FILE:-.env}"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "${ENV_FILE} not found" >&2
  exit 1
fi

CURRENT="$(grep -E '^APIBANK_FERNET_KEYS=' "${ENV_FILE}" | head -n 1 | cut -d= -f2-)"
NEXT="${NAME}:${NEW_KEY}"
if [[ -n "${CURRENT}" ]]; then
  NEXT="${NEXT},${CURRENT}"
fi

sed -i.bak -e "s|^APIBANK_FERNET_KEYS=.*|APIBANK_FERNET_KEYS=${NEXT}|" "${ENV_FILE}"
echo "rotated. New value:"
echo "APIBANK_FERNET_KEYS=${NEXT}"
echo "Restart api/worker/scheduler containers, then re-encrypt secrets and remove old keys."
