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

echo "[INFO] Running integration gate with ${PYTHON_BIN}"
env DEBUG=false ENABLE_DEMO_AUTH=true \
  "${PYTHON_BIN}" -m pytest -c backend/pytest.ini --noconftest -q \
  backend/tests/test_integration.py::TestNonDBEndpoints::test_core_endpoints_accessible \
  backend/tests/test_phase4_observability.py::test_admin_metrics_returns_dashboard_rollups \
  backend/tests/test_phase1_backend.py::test_phase1_document_upload_is_queued_and_status_updates

echo "[PASS] Integration gate passed"
