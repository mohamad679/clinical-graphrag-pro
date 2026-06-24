#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ -x "backend/.venv/bin/python" ]]; then
  PYTHON_BIN="backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "[FAIL] python3 (or backend/.venv/bin/python) is required"
  exit 1
fi

echo "[INFO] Validating Alembic migration graph with ${PYTHON_BIN}"
PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:${PYTHONPATH}}" \
  "${PYTHON_BIN}" - <<'PY'
from alembic.script import ScriptDirectory
from app.core.database import get_alembic_config

script = ScriptDirectory.from_config(get_alembic_config())
heads = script.get_heads()
if len(heads) != 1:
    raise SystemExit(f"[FAIL] Expected exactly one Alembic head, found {len(heads)}: {heads}")
print(f"[PASS] Alembic head is {heads[0]}")
PY

if [[ "${RUN_LIVE_MIGRATION_CHECK:-false}" == "true" ]]; then
  echo "[INFO] Running live migration status check against DATABASE_URL"
  PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:${PYTHONPATH}}" \
    "${PYTHON_BIN}" - <<'PY'
import asyncio
from app.core.database import check_migration_status

status = asyncio.run(check_migration_status())
if status.get("status") != "current":
    raise SystemExit(f"[FAIL] Database migrations are not current: {status}")
print(f"[PASS] Live migration check passed: {status}")
PY
else
  echo "[WARN] RUN_LIVE_MIGRATION_CHECK=false; live database migration check skipped"
fi

