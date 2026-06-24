#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

OUTPUT_DIR="${1:-${OBJECT_STORAGE_BACKUP_DIR:-${ROOT_DIR}/artifacts/backups/object-storage-$(date +%Y%m%d-%H%M%S)}}"
BUCKET="${OBJECT_STORAGE_BUCKET:-${STORAGE_BUCKET:-}}"
PREFIX="${OBJECT_STORAGE_PREFIX:-${STORAGE_PREFIX:-}}"
PROVIDER="${OBJECT_STORAGE_PROVIDER:-${STORAGE_PROVIDER:-s3}}"

mkdir -p "${OUTPUT_DIR}"

if [[ -z "${BUCKET}" ]]; then
  echo "[FAIL] OBJECT_STORAGE_BUCKET or STORAGE_BUCKET must be set"
  exit 1
fi

if command -v aws >/dev/null 2>&1; then
  AWS_ARGS=()
  if [[ -n "${OBJECT_STORAGE_ENDPOINT_URL:-${STORAGE_ENDPOINT_URL:-}}" ]]; then
    AWS_ARGS+=(--endpoint-url "${OBJECT_STORAGE_ENDPOINT_URL:-${STORAGE_ENDPOINT_URL:-}}")
  fi
  SOURCE_PATH="s3://${BUCKET}"
  if [[ -n "${PREFIX}" ]]; then
    SOURCE_PATH="${SOURCE_PATH%/}/${PREFIX#/}"
  fi
  aws "${AWS_ARGS[@]}" s3 sync "${SOURCE_PATH}" "${OUTPUT_DIR}"
  echo "[PASS] ${PROVIDER} backup mirrored with aws cli into ${OUTPUT_DIR}"
  exit 0
fi

if command -v mc >/dev/null 2>&1 && [[ -n "${MINIO_ALIAS:-}" ]]; then
  SOURCE_PATH="${MINIO_ALIAS}/${BUCKET}"
  if [[ -n "${PREFIX}" ]]; then
    SOURCE_PATH="${SOURCE_PATH%/}/${PREFIX#/}"
  fi
  mc mirror "${SOURCE_PATH}" "${OUTPUT_DIR}"
  echo "[PASS] ${PROVIDER} backup mirrored with mc into ${OUTPUT_DIR}"
  exit 0
fi

echo "[FAIL] Neither aws cli nor mc is available for object storage backup"
exit 1

