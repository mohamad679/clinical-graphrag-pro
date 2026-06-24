#!/usr/bin/env bash
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -z "${BASE_URL:-}" ] || [ -z "${TOKEN:-}" ]; then
  . "$SCRIPT_DIR/00_setup.sh"
fi

QUERY="${1:-Check drug interactions between Warfarin and Amoxicillin}"

REQUEST_BODY=$(python3 - "$QUERY" <<'PY'
import json
import sys

print(json.dumps({
    "query": sys.argv[1],
    "workflow_type": "general"
}))
PY
)

printf 'Starting workflow for query: %s\n\n' "$QUERY"

curl -sS -N -X POST "$BASE_URL/agents/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$REQUEST_BODY" | \
while IFS= read -r line; do
  case "$line" in
    data:*)
      data=${line#data: }
      event_type=$(printf '%s' "$data" | python3 -c 'import json, sys
try:
    print(json.load(sys.stdin).get("type", ""))
except Exception:
    print("")
' 2>/dev/null)

      case "$event_type" in
        reasoning)
          title=$(printf '%s' "$data" | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d.get("title", ""))' 2>/dev/null)
          status=$(printf '%s' "$data" | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d.get("status", ""))' 2>/dev/null)
          printf '🧠 [%s] %s\n' "${status:-running}" "$title"
          ;;
        tool_call)
          tool=$(printf '%s' "$data" | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d.get("tool", ""))' 2>/dev/null)
          printf '🔧 Tool: %s\n' "$tool"
          ;;
        synthesis|token)
          content=$(printf '%s' "$data" | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d.get("content", ""), end="")' 2>/dev/null)
          if [ -n "$content" ]; then
            printf '\n%s\n' "$content"
          fi
          ;;
        verification)
          status=$(printf '%s' "$data" | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d.get("status", ""))' 2>/dev/null)
          confidence=$(printf '%s' "$data" | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d.get("confidence_score", ""))' 2>/dev/null)
          printf '\n🔎 Verification: %s (confidence %s)\n' "$status" "$confidence"
          ;;
        workflow_complete|workflow_done)
          answer=$(printf '%s' "$data" | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d.get("answer", "").strip())' 2>/dev/null)
          if [ -n "$answer" ]; then
            printf '\n%s\n' "$answer"
          fi
          printf '\n✅ Workflow complete\n'
          ;;
        error)
          message=$(printf '%s' "$data" | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d.get("content", "").strip())' 2>/dev/null)
          printf '\n❌ %s\n' "$message" >&2
          ;;
      esac
      ;;
  esac
done
