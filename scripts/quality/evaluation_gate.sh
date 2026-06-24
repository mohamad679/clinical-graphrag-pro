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

echo "[INFO] Running internal evaluation gate with ${PYTHON_BIN}"
PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:${PYTHONPATH}}" \
  "${PYTHON_BIN}" backend/scripts/run_internal_evaluation_gate.py
echo "[PASS] Internal evaluation gate passed"
