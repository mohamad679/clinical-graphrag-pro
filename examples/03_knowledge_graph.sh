#!/usr/bin/env bash
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -z "${BASE_URL:-}" ]; then
  BASE_URL="http://localhost/api"
fi

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

pretty_json() {
  python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin), indent=2, sort_keys=True))'
}

ADMIN_EMAIL="${ADMIN_EMAIL:-admin@clinicalgraph.ai}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"

if [ -z "${ADMIN_TOKEN:-}" ]; then
  [ -n "$ADMIN_PASSWORD" ] || fail "Set ADMIN_PASSWORD or ADMIN_TOKEN before running this example."
  LOGIN_PAYLOAD=$(python3 - "$ADMIN_EMAIL" "$ADMIN_PASSWORD" <<'PY'
import json
import sys

print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))
PY
  ) || fail "Failed to build admin login payload."

  LOGIN_RESPONSE=$(curl -fsS -X POST "$BASE_URL/auth/login" \
    -H "Content-Type: application/json" \
    -d "$LOGIN_PAYLOAD") || fail "Admin login failed. Set ADMIN_EMAIL and ADMIN_PASSWORD to valid credentials."

  ADMIN_TOKEN=$(printf '%s' "$LOGIN_RESPONSE" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("access_token", ""))') || fail "Failed to parse admin token."
fi

export BASE_URL
export ADMIN_TOKEN

printf 'Step 1: Seed graph\n'
SEED_RESPONSE=$(curl -fsS -X POST "$BASE_URL/graph/seed" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"patient_id":"Patient_A"}') || fail "Graph seed request failed."
printf '%s' "$SEED_RESPONSE" | pretty_json

printf '\nStep 2: Graph stats\n'
STATS_RESPONSE=$(curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$BASE_URL/graph/stats") || fail "Graph stats request failed."
printf '%s' "$STATS_RESPONSE" | pretty_json

printf '\nStep 3: Temporal snapshot for Patient_A on 2022-06-01\n'
TEMPORAL_RESPONSE=$(curl -fsS -G \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  --data-urlencode "entity=Patient_A" \
  --data-urlencode "date=2022-06-01" \
  "$BASE_URL/graph/temporal") || fail "Temporal graph query failed."
printf '%s' "$TEMPORAL_RESPONSE" | pretty_json

printf '\nStep 4: Patient_A lab trends\n'
LAB_TRENDS_RESPONSE=$(curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$BASE_URL/graph/patients/Patient_A/lab-trends") || fail "Lab trends request failed."
printf '%s' "$LAB_TRENDS_RESPONSE" | pretty_json
