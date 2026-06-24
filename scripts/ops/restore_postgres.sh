#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

BACKUP_FILE="${1:-${POSTGRES_BACKUP_FILE:-}}"
RESTORE_URL="${RESTORE_DATABASE_URL:-${DATABASE_URL:-}}"

if [[ -z "${BACKUP_FILE}" || ! -f "${BACKUP_FILE}" ]]; then
  echo "[FAIL] A valid PostgreSQL backup file is required"
  exit 1
fi

if [[ -z "${RESTORE_URL}" ]]; then
  echo "[FAIL] RESTORE_DATABASE_URL or DATABASE_URL must be set"
  exit 1
fi

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "[FAIL] pg_restore is required for PostgreSQL restores"
  exit 1
fi

pg_restore --clean --if-exists --no-owner --no-privileges --dbname="${RESTORE_URL}" "${BACKUP_FILE}"
echo "[PASS] PostgreSQL restore completed from ${BACKUP_FILE}"

