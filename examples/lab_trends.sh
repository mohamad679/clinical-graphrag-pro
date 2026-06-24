#!/usr/bin/env bash
set -eu

# Clinical GraphRAG Pro — Lab Trends API Example
# Usage: bash examples/lab_trends.sh

BASE_URL="${CLINICAL_API_URL:-http://localhost/api}"
TOKEN="${CLINICAL_TOKEN:-}"

if [ -z "$TOKEN" ]; then
  echo "Set CLINICAL_TOKEN env var first. Get it via:"
  echo "  TOKEN=\$(curl -s -X POST $BASE_URL/auth/login \\"
  echo "    -H 'Content-Type: application/json' \\"
  echo "    -d '{\"email\":\"demo@clinical-graphrag.ai\",\"password\":\"DemoPass2025!\"}' | jq -r '.access_token')"
  exit 1
fi

echo "=== Fetching all lab data for Patient_Anderson ==="
curl -s "$BASE_URL/graph/patients/Patient_Anderson/lab-trends" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo ""
echo "=== Filtering for HbA1c specifically ==="
curl -s "$BASE_URL/graph/patients/Patient_Anderson/lab-trends?lab=HbA1c" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
