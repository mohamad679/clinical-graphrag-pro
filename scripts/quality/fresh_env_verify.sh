#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

FRESH_ENV_DIR="${FRESH_ENV_DIR:-${ROOT_DIR}/.tmp/fresh-env-verify}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

if [[ -e "${FRESH_ENV_DIR}" ]]; then
  echo "[FAIL] FRESH_ENV_DIR already exists: ${FRESH_ENV_DIR}"
  echo "       Choose an empty path with FRESH_ENV_DIR=/path/to/new/env."
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "[FAIL] ${PYTHON_BIN} is required. This repository targets Python 3.12."
  exit 1
fi

echo "[INFO] Creating clean virtual environment at ${FRESH_ENV_DIR}"
"${PYTHON_BIN}" -m venv "${FRESH_ENV_DIR}"
PY="${FRESH_ENV_DIR}/bin/python"

echo "[INFO] Installing pinned backend dependencies"
"${PY}" -m pip install --upgrade pip
"${PY}" -m pip install -r backend/requirements.txt
"${PY}" -m pip install bandit pip-audit

export PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:${PYTHONPATH}}"
export APP_ENV="${APP_ENV:-development}"
export DEBUG="${DEBUG:-true}"
export ENABLE_DEMO_AUTH="${ENABLE_DEMO_AUTH:-true}"
export LLM_PROVIDER="${LLM_PROVIDER:-retrieval-only}"
export JWT_SECRET="${JWT_SECRET:-clinical-graphrag-fresh-env-test-secret-32chars}"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///${ROOT_DIR}/.tmp/fresh-env-verify.sqlite3}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

echo "[INFO] Validating import/runtime metadata"
"${PY}" - <<'PY'
import platform
if platform.python_version_tuple()[:2] != ("3", "12"):
    raise SystemExit(f"[FAIL] Python 3.12 required, got {platform.python_version()}")
print(f"[PASS] Python runtime: {platform.python_version()}")
PY

echo "[INFO] Validating migration graph"
PYTHONPATH="${PYTHONPATH}" "${PY}" - <<'PY'
from alembic.script import ScriptDirectory
from app.core.database import get_alembic_config

script = ScriptDirectory.from_config(get_alembic_config())
heads = script.get_heads()
if len(heads) != 1:
    raise SystemExit(f"[FAIL] Expected one Alembic head, found {heads}")
print(f"[PASS] Alembic head: {heads[0]}")
PY

echo "[INFO] Running database migrations"
(cd backend && "${PY}" -m alembic upgrade head)

echo "[INFO] Running lint"
"${PY}" -m ruff check backend/app backend/tests --ignore=E402,E701,E741,F401,F841

echo "[INFO] Running unit and integration tests with line and branch coverage"
(cd backend && "${PY}" -m pytest tests --cov=app --cov-branch --cov-report=term --cov-report=xml --no-cov-on-fail)

echo "[INFO] Running security-focused tests and scans"
bash scripts/quality/security_gate.sh

echo "[INFO] Running red-team regression tests"
"${PY}" -m pytest -c backend/pytest.ini --no-cov -q \
  backend/tests/test_adversarial_safety.py \
  backend/tests/test_safety_grounding.py \
  backend/tests/test_final_hardening_gate.py \
  backend/tests/test_security_hardening_scope.py

echo "[INFO] Running retrieval benchmark smoke/regression tests"
"${PY}" -m pytest -c backend/pytest.ini --no-cov -q \
  backend/tests/test_retrieval_regression.py \
  backend/tests/test_bm25_hardening.py

echo "[INFO] Running documentation and release-link checks"
"${PY}" -m pytest -c backend/pytest.ini --no-cov -q \
  backend/tests/test_phase7_docs_alignment.py \
  backend/tests/test_phase8_release_readiness.py

echo "[INFO] Running tracked-file secret scan"
bash scripts/check-secrets.sh

echo "[PASS] Fresh environment verification completed"
