#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

echo "[INFO] Running release-readiness validation across Phases 2-7..."
for phase in 2 3 4 5 6 7; do
  echo "[INFO] Executing phase check ${phase}"
  ./scripts/quality/phase_check.sh "${phase}"
done

echo "[INFO] Running migration gate"
bash scripts/quality/migration_gate.sh

echo "[INFO] Running backend quality gate"
bash scripts/quality/backend_gate.sh

echo "[INFO] Running integration gate"
bash scripts/quality/integration_gate.sh

echo "[INFO] Running security gate"
bash scripts/quality/security_gate.sh

if command -v docker >/dev/null 2>&1; then
  docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile production config >/dev/null
  docker compose -f docker-compose.yml -f docker-compose.staging.yml --profile staging config >/dev/null
  echo "[PASS] Docker Compose prod/staging config validation passed"
else
  echo "[WARN] docker not found; compose validation skipped"
fi

if [[ "${RUN_BACKUP_DRILL:-false}" == "true" ]]; then
  echo "[INFO] Running backup and restore drill"
  bash scripts/ops/backup_restore_drill.sh
else
  echo "[WARN] RUN_BACKUP_DRILL=false; backup/restore drill skipped"
fi

if [[ "${RUN_STAGING_SMOKE:-false}" == "true" ]]; then
  echo "[INFO] Running staging smoke flow"
  bash scripts/quality/staging_smoke.sh
else
  echo "[WARN] RUN_STAGING_SMOKE=false; staging smoke flow skipped"
fi

echo "[PASS] Release-readiness validation completed"
