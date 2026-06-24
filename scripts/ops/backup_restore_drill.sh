#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

OUTPUT_ROOT="${1:-${BACKUP_DRILL_OUTPUT_DIR:-${ROOT_DIR}/artifacts/backup-drills/drill-$(date +%Y%m%d-%H%M%S)}}"
mkdir -p "${OUTPUT_ROOT}"

POSTGRES_BACKUP_PATH="${OUTPUT_ROOT}/postgres.dump"

echo "[INFO] Starting backup drill in ${OUTPUT_ROOT}"
bash scripts/ops/backup_postgres.sh "${POSTGRES_BACKUP_PATH}"
bash scripts/ops/backup_object_storage.sh "${OUTPUT_ROOT}/object-storage"
bash scripts/ops/backup_vector_graph.sh "${OUTPUT_ROOT}/vector-graph"

if [[ "${RUN_RESTORE_TEST:-false}" == "true" ]]; then
  echo "[INFO] Running PostgreSQL restore drill"
  bash scripts/ops/restore_postgres.sh "${POSTGRES_BACKUP_PATH}"
  echo "[PASS] Restore drill completed"
else
  echo "[WARN] RUN_RESTORE_TEST=false; restore drill skipped after backup capture"
fi

echo "[PASS] Backup drill artifacts captured in ${OUTPUT_ROOT}"

