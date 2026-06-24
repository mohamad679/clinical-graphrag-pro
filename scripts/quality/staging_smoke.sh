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

if [[ -z "${STAGING_BASE_URL:-}" || -z "${STAGING_ADMIN_EMAIL:-}" || -z "${STAGING_ADMIN_PASSWORD:-}" ]]; then
  if [[ "${ALLOW_GATE_SKIPS:-false}" == "true" ]]; then
    echo "[WARN] STAGING_BASE_URL / STAGING_ADMIN_EMAIL / STAGING_ADMIN_PASSWORD not set; staging smoke skipped"
    exit 0
  fi
  echo "[FAIL] STAGING_BASE_URL, STAGING_ADMIN_EMAIL, and STAGING_ADMIN_PASSWORD are required"
  exit 1
fi

echo "[INFO] Running staging smoke flow against ${STAGING_BASE_URL}"
EXTRA_ARGS=()
if [[ "${STAGING_INSECURE_SSL:-false}" == "true" ]]; then
  EXTRA_ARGS+=(--insecure)
fi
PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:${PYTHONPATH}}" \
  "${PYTHON_BIN}" backend/scripts/staging_smoke.py \
  --base-url "${STAGING_BASE_URL}" \
  --email "${STAGING_ADMIN_EMAIL}" \
  --password "${STAGING_ADMIN_PASSWORD}" \
  --timeout-seconds "${STAGING_TIMEOUT_SECONDS:-300}" \
  "${EXTRA_ARGS[@]}"

echo "[PASS] Staging smoke flow passed"
