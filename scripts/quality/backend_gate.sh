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

echo "[INFO] Using Python: ${PYTHON_BIN}"

"${PYTHON_BIN}" -m compileall backend/app >/dev/null
echo "[PASS] Python compile check passed for backend/app"

if "${PYTHON_BIN}" -m ruff --version >/dev/null 2>&1; then
  "${PYTHON_BIN}" -m ruff check backend/app backend/tests
  echo "[PASS] Ruff lint checks passed"
else
  echo "[WARN] Ruff not installed in current environment; lint step skipped"
fi

env DEBUG=false ENABLE_DEMO_AUTH=true \
  "${PYTHON_BIN}" -m pytest -c backend/pytest.ini --noconftest -q \
  backend/tests/test_phase3_support_endpoints.py \
  backend/tests/test_phase4_observability.py \
  backend/tests/test_phase4_retrieval.py \
  backend/tests/test_agents.py \
  backend/tests/test_entity_normalization.py \
  backend/tests/test_phase6_quality_gate.py

echo "[PASS] Stable backend test suite passed"

bash scripts/quality/evaluation_gate.sh
