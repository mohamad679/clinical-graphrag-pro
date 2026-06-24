#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export LC_ALL=C
export LANG=C
ARTIFACT_DIR="${ROOT_DIR}/reports/release_artifacts"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACT_PATH="${ARTIFACT_DIR}/clinical-graphrag-pro-portfolio-${TIMESTAMP}.tar.gz"

mkdir -p "${ARTIFACT_DIR}"

tar \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='backend/.env' \
  --exclude='backend/.venv' \
  --exclude='**/__pycache__' \
  --exclude='**/.pytest_cache' \
  --exclude='**/.ruff_cache' \
  --exclude='backend/uploads' \
  --exclude='uploads' \
  --exclude='backend/local_ui.sqlite3*' \
  --exclude='backend/*_test.db' \
  --exclude='data/vector_store' \
  --exclude='backend/data/bm25_store' \
  -czf "${ARTIFACT_PATH}" \
  -C "${ROOT_DIR}" \
  README.md backend/app backend/alembic backend/requirements.txt backend/requirements-dev.txt docs scripts .github docker-compose.yml docker-compose.prod.yml

SHA256="$(shasum -a 256 "${ARTIFACT_PATH}" | awk '{print $1}')"
printf '{"artifact_path":"%s","sha256":"%s"}\n' "${ARTIFACT_PATH}" "${SHA256}"
