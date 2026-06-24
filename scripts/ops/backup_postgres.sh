#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

DATABASE_BACKUP_URL="${POSTGRES_BACKUP_URL:-${DATABASE_URL:-}}"
OUTPUT_FILE="${1:-${POSTGRES_BACKUP_FILE:-${ROOT_DIR}/artifacts/backups/postgres-$(date +%Y%m%d-%H%M%S).dump}}"

if [[ -z "${DATABASE_BACKUP_URL}" ]]; then
  echo "[FAIL] POSTGRES_BACKUP_URL or DATABASE_URL must be set"
  exit 1
fi

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "[FAIL] pg_dump is required for PostgreSQL backups"
  exit 1
fi

mkdir -p "$(dirname "${OUTPUT_FILE}")"
pg_dump "${DATABASE_BACKUP_URL}" --format=custom --no-owner --no-privileges --file="${OUTPUT_FILE}"
echo "[PASS] PostgreSQL backup written to ${OUTPUT_FILE}"

