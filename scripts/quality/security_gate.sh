#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

STRICT_SCAN="${REQUIRE_SECURITY_SCAN:-false}"

if [[ -x "backend/.venv/bin/python" ]]; then
  PYTHON_BIN="backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "[FAIL] python3 (or backend/.venv/bin/python) is required"
  exit 1
fi

echo "[INFO] Running secrets gate"
bash scripts/check-secrets.sh
echo "[PASS] Secrets gate passed"

echo "[INFO] Running security-focused tests"
env DEBUG=false ENABLE_DEMO_AUTH=true \
  "${PYTHON_BIN}" -m pytest -c backend/pytest.ini --no-cov -q \
  backend/tests/test_phase0_security.py
echo "[PASS] Security-focused pytest suite passed"

if "${PYTHON_BIN}" -m bandit --version >/dev/null 2>&1; then
  echo "[INFO] Running Bandit"
  "${PYTHON_BIN}" -m bandit -q -r backend/app
  echo "[PASS] Bandit scan passed"
elif [[ "${STRICT_SCAN}" == "true" ]]; then
  echo "[FAIL] Bandit is required when REQUIRE_SECURITY_SCAN=true"
  exit 1
else
  echo "[WARN] Bandit not installed; static security scan skipped"
fi

if "${PYTHON_BIN}" -m pip_audit --version >/dev/null 2>&1; then
  echo "[INFO] Running pip-audit"
  "${PYTHON_BIN}" -m pip_audit -r backend/requirements.txt --progress-spinner off
  echo "[PASS] Dependency vulnerability scan passed"
elif [[ "${STRICT_SCAN}" == "true" ]]; then
  echo "[FAIL] pip-audit is required when REQUIRE_SECURITY_SCAN=true"
  exit 1
else
  echo "[WARN] pip-audit not installed; dependency scan skipped"
fi
