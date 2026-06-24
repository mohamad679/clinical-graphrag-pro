#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/backend/.venv/bin/python}"
SUMMARY_DIR="${ROOT_DIR}/reports/release_gates"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SUMMARY_PATH="${SUMMARY_DIR}/portfolio_release_gate_${TIMESTAMP}.json"
mkdir -p "${SUMMARY_DIR}"

COMMIT_HASH="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || true)"
DIRTY_TREE="false"
if [[ -n "$(git -C "${ROOT_DIR}" status --short 2>/dev/null || true)" ]]; then
  DIRTY_TREE="true"
fi

declare -a STEP_NAMES=()
declare -a STEP_STATUSES=()
declare -a STEP_COMMANDS=()
ARTIFACT_PATH=""
ARTIFACT_SHA256=""

json_escape() {
  "${PYTHON_BIN}" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

write_summary() {
  local overall_status="$1"
  local steps_json="[]"
  steps_json="$(
    "${PYTHON_BIN}" - "$overall_status" "$TIMESTAMP" "$COMMIT_HASH" "$DIRTY_TREE" "$ARTIFACT_PATH" "$ARTIFACT_SHA256" "${STEP_NAMES[@]}" -- "${STEP_STATUSES[@]}" -- "${STEP_COMMANDS[@]}" <<'PY'
import json
import sys

overall, timestamp, commit, dirty, artifact_path, artifact_sha, *rest = sys.argv[1:]
first_sep = rest.index("--")
names = rest[:first_sep]
rest = rest[first_sep + 1:]
second_sep = rest.index("--")
statuses = rest[:second_sep]
commands = rest[second_sep + 1:]
steps = [
    {"name": name, "status": status, "command": command}
    for name, status, command in zip(names, statuses, commands)
]
payload = {
    "timestamp": timestamp,
    "commit_hash": commit,
    "dirty_tree": dirty == "true",
    "overall_status": overall,
    "release_integrity_status": next((s["status"] for s in steps if s["name"] == "release_integrity"), "not_run"),
    "type_check_status": next((s["status"] for s in steps if s["name"] == "pyright"), "not_run"),
    "test_status": next((s["status"] for s in steps if s["name"] == "pytest_backend"), "not_run"),
    "benchmark_gate_status": next((s["status"] for s in steps if s["name"] == "retrieval_benchmark_v2"), "not_run"),
    "artifact_path": artifact_path or None,
    "artifact_sha256": artifact_sha or None,
    "steps": steps,
    "optional_steps": [
        "staging smoke",
        "backup drill",
        "restore drill",
        "live provider generation evaluation",
    ],
}
print(json.dumps(payload, indent=2))
PY
  )"
  printf '%s\n' "${steps_json}" > "${SUMMARY_PATH}"
}

run_required() {
  local name="$1"
  shift
  local command_text="$*"
  STEP_NAMES+=("${name}")
  STEP_COMMANDS+=("${command_text}")
  printf '\n[RUN] %s\n%s\n' "${name}" "${command_text}"
  if "$@"; then
    STEP_STATUSES+=("passed")
  else
    STEP_STATUSES+=("failed")
    write_summary "failed"
    printf '\n[FAIL] %s\nSummary: %s\n' "${name}" "${SUMMARY_PATH}"
    exit 1
  fi
}

run_required release_integrity "${PYTHON_BIN}" "${ROOT_DIR}/scripts/check_release_integrity.py"
run_required ruff "${PYTHON_BIN}" -m ruff check "${ROOT_DIR}/backend/app" "${ROOT_DIR}/backend/tests" "${ROOT_DIR}/scripts"
run_required pyright "${PYTHON_BIN}" -m pyright -p "${ROOT_DIR}/backend/pyrightconfig.json"
run_required pytest_backend "${PYTHON_BIN}" -m pytest -c "${ROOT_DIR}/backend/pytest.ini" --no-cov "${ROOT_DIR}/backend/tests"
run_required pytest_red_team "${PYTHON_BIN}" -m pytest -c "${ROOT_DIR}/backend/pytest.ini" --no-cov \
  "${ROOT_DIR}/backend/tests/test_adversarial_safety.py" \
  "${ROOT_DIR}/backend/tests/test_safety_grounding.py" \
  "${ROOT_DIR}/backend/tests/test_final_hardening_gate.py" \
  "${ROOT_DIR}/backend/tests/test_security_hardening_scope.py"
run_required retrieval_benchmark_v2 "${PYTHON_BIN}" "${ROOT_DIR}/scripts/evaluate_retrieval_v2.py" \
  --dataset "${ROOT_DIR}/backend/data/synthetic_retrieval_benchmark_v2.json" \
  --output "${ROOT_DIR}/results/portfolio_gate_retrieval_benchmark_${TIMESTAMP}.json"

STEP_NAMES+=("build_release_artifact")
STEP_COMMANDS+=("bash ${ROOT_DIR}/scripts/quality/build_release_artifact.sh")
printf '\n[RUN] build_release_artifact\n'
artifact_json="$(bash "${ROOT_DIR}/scripts/quality/build_release_artifact.sh")"
ARTIFACT_PATH="$("${PYTHON_BIN}" -c 'import json,sys; print(json.loads(sys.stdin.read())["artifact_path"])' <<<"${artifact_json}")"
ARTIFACT_SHA256="$("${PYTHON_BIN}" -c 'import json,sys; print(json.loads(sys.stdin.read())["sha256"])' <<<"${artifact_json}")"
STEP_STATUSES+=("passed")

write_summary "passed"

printf '\nPortfolio Release Gate Summary\n'
printf 'Step\tStatus\n'
for idx in "${!STEP_NAMES[@]}"; do
  printf '%s\t%s\n' "${STEP_NAMES[$idx]}" "${STEP_STATUSES[$idx]}"
done
printf 'Summary JSON: %s\n' "${SUMMARY_PATH}"
printf 'Artifact: %s\n' "${ARTIFACT_PATH}"
printf 'Artifact SHA-256: %s\n' "${ARTIFACT_SHA256}"
