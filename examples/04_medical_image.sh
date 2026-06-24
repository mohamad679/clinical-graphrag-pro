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

DOWNLOAD_PATH="${DOWNLOAD_PATH:-/tmp/sample_xray.png}"
IMAGE_SOURCE_URL="https://upload.wikimedia.org/wikipedia/commons/5/57/Chest_Xray_PA_3-8-2010.png"

printf 'Downloading sample image to %s\n' "$DOWNLOAD_PATH"
curl -fsSL -o "$DOWNLOAD_PATH" "$IMAGE_SOURCE_URL" || fail "Failed to download the sample chest X-ray."

printf 'Uploading image\n'
UPLOAD_RESPONSE=$(curl -fsS -X POST "$BASE_URL/images/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$DOWNLOAD_PATH;type=image/png") || fail "Image upload failed."

IMAGE_ID=$(printf '%s' "$UPLOAD_RESPONSE" | json_get id) || fail "Could not parse image id."
[ -n "$IMAGE_ID" ] || fail "Upload response did not include an image id."
printf 'Image ID: %s\n' "$IMAGE_ID"

ANALYZE_PAYLOAD='{"additional_context":"Public domain PA chest radiograph used for API example automation."}'

printf 'Requesting AI analysis\n'
ANALYZE_RESPONSE=$(curl -fsS -X POST "$BASE_URL/images/$IMAGE_ID/analyze" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$ANALYZE_PAYLOAD") || fail "Image analysis dispatch failed."
printf '%s\n' "$ANALYZE_RESPONSE"

WAITED=0
ANALYSIS_STATUS=""
IMAGE_RESPONSE=""

while [ "$WAITED" -lt 120 ]; do
  IMAGE_RESPONSE=$(curl -fsS \
    -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/images/$IMAGE_ID") || fail "Image status request failed."

  ANALYSIS_STATUS=$(printf '%s' "$IMAGE_RESPONSE" | json_get analysis_status) || fail "Could not parse analysis_status."
  printf 'Analysis status: %s\n' "$ANALYSIS_STATUS"

  if [ "$ANALYSIS_STATUS" = "ai_generated" ]; then
    break
  fi

  if [ "$ANALYSIS_STATUS" = "failed" ]; then
    LAST_ERROR=$(printf '%s' "$IMAGE_RESPONSE" | json_get last_error) || fail "Image analysis failed."
    fail "Image analysis failed: ${LAST_ERROR:-unknown error}"
  fi

  sleep 2
  WAITED=$((WAITED + 2))
done

[ "$ANALYSIS_STATUS" = "ai_generated" ] || fail "Image analysis did not complete within 120 seconds."

printf '\nFindings summary:\n'
printf '%s' "$IMAGE_RESPONSE" | python3 -c '
import json
import sys

data = json.load(sys.stdin)
analysis = data.get("analysis_result") or {}
print(analysis.get("summary", "").strip() or "(no summary returned)")
findings = analysis.get("findings") or []
if findings:
    print("")
    print("Findings:")
    for index, finding in enumerate(findings, start=1):
        desc = finding.get("description", "")
        location = finding.get("location", "")
        severity = finding.get("severity", "")
        confidence = finding.get("confidence", "")
        print(f"{index}. {desc} | location={location or \"n/a\"} | severity={severity or \"n/a\"} | confidence={confidence}")
'
