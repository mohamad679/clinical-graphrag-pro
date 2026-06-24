#!/usr/bin/env bash

# Source this file to export BASE_URL and TOKEN for the example scripts.

fail() {
  printf 'Error: %s\n' "$1" >&2
  return 1 2>/dev/null || exit 1
}

json_get() {
  python3 -c '
import json
import sys

path = [part for part in sys.argv[1].split(".") if part]
data = json.load(sys.stdin)
for part in path:
    if isinstance(data, list):
        data = data[int(part)]
    elif isinstance(data, dict):
        data = data.get(part)
    else:
        data = None
    if data is None:
        break

if data is None:
    print("")
elif isinstance(data, (dict, list)):
    print(json.dumps(data))
else:
    print(data)
' "$1"
}

pretty_json() {
  python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin), indent=2, sort_keys=True))'
}

BASE_URL="${BASE_URL:-http://localhost/api}"
EMAIL="${EMAIL:-physician@clinicalgraph.ai}"
PASSWORD="${PASSWORD:-}"
[ -n "$PASSWORD" ] || fail "Set PASSWORD to a valid demo account password or bootstrap an admin first."

LOGIN_PAYLOAD=$(python3 - "$EMAIL" "$PASSWORD" <<'PY'
import json
import sys

print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))
PY
) || fail "Failed to build login payload."

LOGIN_RESPONSE=$(curl -fsS -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "$LOGIN_PAYLOAD") || fail "Login failed for $EMAIL. Set EMAIL and PASSWORD to valid credentials."

TOKEN=$(printf '%s' "$LOGIN_RESPONSE" | json_get access_token) || fail "Failed to parse login response."
[ -n "$TOKEN" ] || fail "Login response did not include access_token."

REFRESH_TOKEN=$(printf '%s' "$LOGIN_RESPONSE" | json_get refresh_token) || fail "Failed to parse refresh_token."
SESSION_ID=$(printf '%s' "$LOGIN_RESPONSE" | json_get session_id) || fail "Failed to parse session_id."
TOKEN_TYPE=$(printf '%s' "$LOGIN_RESPONSE" | json_get token_type) || fail "Failed to parse token_type."
EXPIRES_IN=$(printf '%s' "$LOGIN_RESPONSE" | json_get expires_in) || fail "Failed to parse expires_in."
USER_NAME=$(printf '%s' "$LOGIN_RESPONSE" | json_get user.name) || fail "Failed to parse user.name."
USER_ROLE=$(printf '%s' "$LOGIN_RESPONSE" | json_get user.role) || fail "Failed to parse user.role."

export BASE_URL
export EMAIL
export TOKEN
export REFRESH_TOKEN
export SESSION_ID
export TOKEN_TYPE
export EXPIRES_IN
export USER_NAME
export USER_ROLE

HEALTH_RESPONSE=$(curl -fsS "$BASE_URL/health") || fail "Health check failed at $BASE_URL/health."

printf 'BASE_URL=%s\n' "$BASE_URL"
printf 'Authenticated as %s (%s)\n' "${USER_NAME:-$EMAIL}" "${USER_ROLE:-unknown}"
printf 'Session ID: %s\n' "${SESSION_ID:-unknown}"
printf 'Token expires in: %s seconds\n' "${EXPIRES_IN:-unknown}"
printf 'Health check:\n'
printf '%s' "$HEALTH_RESPONSE" | pretty_json || fail "Failed to pretty-print health response."
