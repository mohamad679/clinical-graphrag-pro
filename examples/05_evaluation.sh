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

DATASET_FILE="$SCRIPT_DIR/../backend/data/golden_evaluation_dataset.jsonl"
DATASET_INDEX="${DATASET_INDEX:-0}"
TOP_K="${TOP_K:-5}"

[ -f "$DATASET_FILE" ] || fail "Golden dataset not found at $DATASET_FILE."

SAMPLE=$(python3 - "$DATASET_FILE" "$DATASET_INDEX" <<'PY'
import json
import sys

path = sys.argv[1]
index = int(sys.argv[2])

with open(path, "r", encoding="utf-8") as handle:
    rows = [json.loads(line) for line in handle if line.strip()]

if not rows:
    raise SystemExit("Golden dataset is empty.")

if index < 0 or index >= len(rows):
    raise SystemExit(f"DATASET_INDEX must be between 0 and {len(rows) - 1}.")

print(json.dumps(rows[index]))
PY
) || fail "Failed to load a sample from the golden dataset."

QUESTION=$(printf '%s' "$SAMPLE" | json_get question) || fail "Could not parse question from golden dataset."
GROUND_TRUTH=$(printf '%s' "$SAMPLE" | json_get ground_truth) || fail "Could not parse ground_truth from golden dataset."

REQUEST_BODY=$(python3 - "$QUESTION" "$TOP_K" <<'PY'
import json
import sys

print(json.dumps({
    "query": sys.argv[1],
    "top_k": int(sys.argv[2]),
}))
PY
) || fail "Failed to build evaluation payload."

EVAL_RESPONSE=$(curl -fsS -X POST "$BASE_URL/eval/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$REQUEST_BODY") || fail "Evaluation request failed."

printf 'Question: %s\n' "$QUESTION"
printf 'Ground truth reference: %s\n\n' "$GROUND_TRUTH"

printf '%s' "$EVAL_RESPONSE" | python3 -c '
import json
import sys

def indicator(score: float) -> str:
    if score >= 0.8:
        return "✅"
    if score >= 0.65:
        return "⚠️"
    return "❌"

data = json.load(sys.stdin)
metrics = [
    ("Faithfulness", data["faithfulness"]["score"]),
    ("Relevance", data["relevance"]["score"]),
    ("Citation Accuracy", data["citation_accuracy"]["score"]),
    ("Context Precision", data["context_precision"]["score"]),
]

for label, score in metrics:
    print(f"{indicator(float(score))} {label}: {float(score):.2f}")

print(f"\nOverall Score: {float(data.get(\"overall_score\", 0.0)):.2f}")
'
