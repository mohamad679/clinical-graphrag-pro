#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

OUTPUT_DIR="${1:-${VECTOR_GRAPH_BACKUP_DIR:-${ROOT_DIR}/artifacts/backups/vector-graph-$(date +%Y%m%d-%H%M%S)}}"
mkdir -p "${OUTPUT_DIR}/qdrant" "${OUTPUT_DIR}/neo4j"

QDRANT_REQUIRED="${REQUIRE_QDRANT_BACKUP:-false}"
NEO4J_REQUIRED="${REQUIRE_NEO4J_BACKUP:-false}"

if [[ -n "${QDRANT_URL:-}" && -n "${QDRANT_COLLECTION:-}" ]]; then
  if ! command -v curl >/dev/null 2>&1; then
    echo "[FAIL] curl is required for Qdrant backups"
    exit 1
  fi
  CURL_ARGS=(-fsSL)
  if [[ -n "${QDRANT_API_KEY:-}" ]]; then
    CURL_ARGS+=(-H "api-key: ${QDRANT_API_KEY}")
  fi
  RESPONSE_FILE="${OUTPUT_DIR}/qdrant/snapshot-response.json"
  curl "${CURL_ARGS[@]}" -X POST "${QDRANT_URL%/}/collections/${QDRANT_COLLECTION}/snapshots" > "${RESPONSE_FILE}"
  if command -v python3 >/dev/null 2>&1; then
    SNAPSHOT_NAME="$(python3 -c 'import json,sys; data=json.load(open(sys.argv[1], "r", encoding="utf-8")); print(data.get("result", {}).get("name", ""))' "${RESPONSE_FILE}")"
    if [[ -n "${SNAPSHOT_NAME}" ]]; then
      curl "${CURL_ARGS[@]}" "${QDRANT_URL%/}/collections/${QDRANT_COLLECTION}/snapshots/${SNAPSHOT_NAME}" \
        --output "${OUTPUT_DIR}/qdrant/${SNAPSHOT_NAME}"
      echo "[PASS] Qdrant snapshot downloaded to ${OUTPUT_DIR}/qdrant/${SNAPSHOT_NAME}"
    else
      echo "[WARN] Qdrant snapshot created but snapshot name could not be extracted; see ${RESPONSE_FILE}"
    fi
  fi
elif [[ "${QDRANT_REQUIRED}" == "true" ]]; then
  echo "[FAIL] QDRANT_URL and QDRANT_COLLECTION are required for vector backup"
  exit 1
else
  echo "[WARN] Qdrant backup skipped; QDRANT_URL or QDRANT_COLLECTION not set"
fi

if command -v neo4j-admin >/dev/null 2>&1; then
  NEO4J_DATABASE_NAME="${NEO4J_DATABASE:-neo4j}"
  neo4j-admin database dump "${NEO4J_DATABASE_NAME}" --to-path="${OUTPUT_DIR}/neo4j"
  echo "[PASS] Neo4j dump written to ${OUTPUT_DIR}/neo4j"
elif [[ "${NEO4J_REQUIRED}" == "true" ]]; then
  echo "[FAIL] neo4j-admin is required for graph backups"
  exit 1
else
  echo "[WARN] Neo4j backup skipped; neo4j-admin is not installed"
fi

