#!/usr/bin/env bash
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -z "${BASE_URL:-}" ] || [ -z "${TOKEN:-}" ]; then
  . "$SCRIPT_DIR/00_setup.sh"
fi

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

DOC_PATH="$SCRIPT_DIR/sample_docs/discharge_summary.txt"
[ -f "$DOC_PATH" ] || fail "Sample document not found at $DOC_PATH."

printf 'Uploading %s\n' "$DOC_PATH"
UPLOAD_RESPONSE=$(curl -fsS -X POST "$BASE_URL/documents/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$DOC_PATH;type=text/plain") || fail "Document upload failed."

DOC_ID=$(printf '%s' "$UPLOAD_RESPONSE" | json_get id) || fail "Could not parse document id."
[ -n "$DOC_ID" ] || fail "Upload response did not include a document id."
printf 'Document ID: %s\n' "$DOC_ID"

WAITED=0
STATUS=""

while [ "$WAITED" -lt 60 ]; do
  STATUS_RESPONSE=$(curl -fsS \
    -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/documents/$DOC_ID/status") || fail "Status request failed."

  STATUS=$(printf '%s' "$STATUS_RESPONSE" | json_get status) || fail "Could not parse document status."
  STAGE=$(printf '%s' "$STATUS_RESPONSE" | json_get stage) || fail "Could not parse document stage."
  PROGRESS=$(printf '%s' "$STATUS_RESPONSE" | json_get progress) || fail "Could not parse document progress."

  printf 'Status: %s | Stage: %s | Progress: %s%%\n' "$STATUS" "${STAGE:-unknown}" "${PROGRESS:-0}"

  if [ "$STATUS" = "ready" ]; then
    break
  fi

  if [ "$STATUS" = "error" ]; then
    ERROR_MESSAGE=$(printf '%s' "$STATUS_RESPONSE" | json_get error_message) || fail "Document processing failed."
    fail "Document processing failed: ${ERROR_MESSAGE:-unknown error}"
  fi

  sleep 2
  WAITED=$((WAITED + 2))
done

[ "$STATUS" = "ready" ] || fail "Document did not reach ready status within 60 seconds."

CHAT_PAYLOAD=$(python3 - "$DOC_ID" <<'PY'
import json
import sys

print(json.dumps({
    "message": "Summarize Robert Chen's NSTEMI hospitalization and list the discharge medications with follow-up needs.",
    "attached_document_id": sys.argv[1]
}))
PY
) || fail "Failed to build chat payload."

CHAT_RESPONSE=$(curl -fsS -X POST "$BASE_URL/chat/sync" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$CHAT_PAYLOAD") || fail "Synchronous chat request failed."

printf '\nAnswer:\n'
printf '%s' "$CHAT_RESPONSE" | python3 -c '
import json
import sys

data = json.load(sys.stdin)
print(data.get("answer", "").strip())
print("")
print("Sources:")
sources = data.get("sources") or []
if not sources:
    print("(none returned)")
else:
    for index, source in enumerate(sources, start=1):
        text = (source.get("text") or "").replace("\n", " ").strip()
        if len(text) > 180:
            text = text[:177] + "..."
        print(f"{index}. {source.get(\"document_name\", \"unknown\")} | chunk {source.get(\"chunk_index\", \"?\")} | score {source.get(\"relevance_score\", \"n/a\")}")
        print(text)
'
