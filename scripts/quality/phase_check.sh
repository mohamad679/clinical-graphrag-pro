#!/usr/bin/env bash
set -euo pipefail

PHASE="${1:-}"

if [[ -z "${PHASE}" ]]; then
  echo "Usage: $0 <phase-number>"
  echo "Example: $0 1"
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

pass() {
  printf '[PASS] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1"
  exit 1
}

check_file_exists() {
  local file_path="$1"
  if [[ -f "${file_path}" ]]; then
    pass "Found ${file_path}"
  else
    fail "Missing ${file_path}"
  fi
}

detect_python() {
  if [[ -x "backend/.venv/bin/python" ]]; then
    echo "backend/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  fail "python3 (or backend/.venv/bin/python) is required"
}

phase_1_checks() {
  echo "Running Phase 1 validation checks..."
  local py
  py="$(detect_python)"

  check_file_exists "docs/remediation-plan.md"
  check_file_exists "docs/phase-status.md"
  check_file_exists "scripts/quality/phase_check.sh"

  "${py}" -m compileall backend/app >/dev/null
  pass "Python compile check passed for backend/app"

  if command -v docker >/dev/null 2>&1; then
    docker compose config >/dev/null
    pass "docker compose config parsed successfully"
  else
    pass "docker not found; compose parse check skipped"
  fi

  echo "Phase 1 validation completed."
}

phase_2_checks() {
  echo "Running Phase 2 validation checks..."
  local py
  py="$(detect_python)"

  check_file_exists "backend/app/api/admin.py"
  check_file_exists "backend/app/api/images.py"
  check_file_exists "backend/app/core/auth.py"
  check_file_exists "frontend/public/js/components/app-layout.js"
  check_file_exists "frontend/public/js/components/chat-interface.js"

  "${py}" -m compileall backend/app >/dev/null
  pass "Python compile check passed for backend/app"

  if ! DEBUG=false ENABLE_DEMO_AUTH=true "${py}" -m pytest -c backend/pytest.ini --noconftest \
    backend/tests/test_auth.py \
    backend/tests/test_security.py \
    -q; then
    fail "Phase 2 targeted pytest suite failed"
  fi
  pass "Phase 2 targeted pytest suite passed"

  if ! rg -n "async def admin_health\\(_user: User = Depends\\(require_admin\\)\\)" backend/app/api/admin.py >/dev/null; then
    fail "Admin health endpoint is not protected with require_admin"
  fi
  if ! rg -n "async def admin_metrics\\(_user: User = Depends\\(require_admin\\)\\)" backend/app/api/admin.py >/dev/null; then
    fail "Admin metrics endpoint is not protected with require_admin"
  fi
  if ! rg -n "async def admin_sessions\\(_user: User = Depends\\(require_admin\\)\\)" backend/app/api/admin.py >/dev/null; then
    fail "Admin sessions endpoint is not protected with require_admin"
  fi
  if ! rg -n "async def admin_config\\(_user: User = Depends\\(require_admin\\)\\)" backend/app/api/admin.py >/dev/null; then
    fail "Admin config endpoint is not protected with require_admin"
  fi
  pass "Admin endpoints are protected with require_admin"

  if rg -n "innerHTML = .*\\$\\{this\\.attachedFile\\.name\\}" frontend/public/js/components/chat-interface.js >/dev/null; then
    fail "Unsafe attachedFile.name innerHTML interpolation still detected"
  fi
  pass "No raw attachedFile.name interpolation detected in chat-interface.js"

  echo "Phase 2 validation completed."
}

phase_3_checks() {
  echo "Running Phase 3 validation checks..."
  local py
  py="$(detect_python)"

  check_file_exists "backend/app/api/chat.py"
  check_file_exists "backend/app/api/documents.py"
  check_file_exists "backend/app/services/vector_store.py"
  check_file_exists "backend/tests/test_phase3_correctness.py"

  "${py}" -m compileall backend/app >/dev/null
  pass "Python compile check passed for backend/app"

  if ! DEBUG=false ENABLE_DEMO_AUTH=true "${py}" -m pytest -c backend/pytest.ini --noconftest \
    backend/tests/test_phase3_correctness.py \
    -q; then
    fail "Phase 3 targeted pytest suite failed"
  fi
  pass "Phase 3 targeted pytest suite passed"

  if rg -n "ann\\.notes" backend/app/api/chat.py >/dev/null; then
    fail "Legacy annotation field ann.notes still present in chat image flow"
  fi
  if ! rg -n "ann\\.description" backend/app/api/chat.py >/dev/null; then
    fail "Image annotation description is not used in chat image context"
  fi
  pass "Image annotation mapping uses description field"

  if rg -n "accept=\"[^\"]*\\.docx" frontend/public/js/components/chat-interface.js >/dev/null; then
    fail "Frontend document input still accepts .docx while backend rejects it"
  fi
  pass "Frontend document input matches backend supported extensions"

  if ! rg -n "mark_document_deleted\\(" backend/app/api/documents.py >/dev/null; then
    fail "Document lifecycle does not invalidate vector entries"
  fi
  pass "Document lifecycle invalidates vector entries"

  echo "Phase 3 validation completed."
}

phase_4_checks() {
  echo "Running Phase 4 validation checks..."
  local py
  py="$(detect_python)"

  check_file_exists "backend/app/services/query_engine.py"
  check_file_exists "backend/app/services/bm25_index.py"
  check_file_exists "backend/app/api/documents.py"
  check_file_exists "backend/tests/test_phase4_retrieval.py"

  "${py}" -m compileall backend/app >/dev/null
  pass "Python compile check passed for backend/app"

  if ! DEBUG=false ENABLE_DEMO_AUTH=true "${py}" -m pytest -c backend/pytest.ini --noconftest \
    backend/tests/test_phase4_retrieval.py \
    -q; then
    fail "Phase 4 targeted pytest suite failed"
  fi
  pass "Phase 4 targeted pytest suite passed"

  if ! rg -n "bm25_index\\.add_document\\(" backend/app/api/documents.py >/dev/null; then
    fail "BM25 indexing is not wired into document ingestion"
  fi
  pass "BM25 indexing is wired into document ingestion"

  if ! rg -n "bm25_index\\.mark_document_deleted\\(" backend/app/api/documents.py >/dev/null; then
    fail "BM25 tombstoning is not wired into document deletion/dedupe"
  fi
  pass "BM25 tombstoning is wired into document deletion/dedupe"

  if ! rg -n "key=lambda x: x\\.get\\(\"vector_score\", 0\\.0\\)" backend/app/services/query_engine.py >/dev/null; then
    fail "Vector-only retrieval path is not sorted by vector_score"
  fi
  pass "Vector-only retrieval path sorts by vector_score"

  echo "Phase 4 validation completed."
}

phase_5_checks() {
  echo "Running Phase 5 validation checks..."
  local py
  py="$(detect_python)"

  check_file_exists "Makefile"
  check_file_exists "docker-compose.yml"
  check_file_exists "docker-compose.dev.yml"
  check_file_exists "backend/requirements.txt"
  check_file_exists "backend/tests/test_phase5_reliability.py"

  "${py}" -m compileall backend/app >/dev/null
  pass "Python compile check passed for backend/app"

  if ! DEBUG=false ENABLE_DEMO_AUTH=true "${py}" -m pytest -c backend/pytest.ini --noconftest \
    backend/tests/test_phase5_reliability.py \
    -q; then
    fail "Phase 5 targeted pytest suite failed"
  fi
  pass "Phase 5 targeted pytest suite passed"

  if ! make -n test >/dev/null; then
    fail "Makefile test target is not renderable"
  fi
  pass "Makefile test target is renderable"

  if command -v docker >/dev/null 2>&1; then
    if ! docker compose -f docker-compose.yml -f docker-compose.dev.yml config >/dev/null; then
      fail "Docker compose merged config is invalid"
    fi
    pass "Docker compose merged config is valid"
  else
    pass "docker not found; compose merged config check skipped"
  fi

  echo "Phase 5 validation completed."
}

phase_6_checks() {
  echo "Running Phase 6 validation checks..."
  local py
  py="$(detect_python)"

  check_file_exists "scripts/quality/backend_gate.sh"
  check_file_exists "scripts/quality/evaluation_gate.sh"
  check_file_exists "backend/tests/test_phase6_quality_gate.py"
  check_file_exists "backend/tests/test_agents.py"
  check_file_exists "backend/tests/test_entity_normalization.py"

  "${py}" -m compileall backend/app >/dev/null
  pass "Python compile check passed for backend/app"

  if ! DEBUG=false ENABLE_DEMO_AUTH=true "${py}" -m pytest -c backend/pytest.ini --noconftest \
    backend/tests/test_phase6_quality_gate.py \
    -q; then
    fail "Phase 6 quality-gate pytest checks failed"
  fi
  pass "Phase 6 quality-gate pytest checks passed"

  if ! bash scripts/quality/backend_gate.sh; then
    fail "Backend quality gate script failed"
  fi
  pass "Backend quality gate script passed"

  if ! rg -n "evaluation_gate\\.sh" scripts/quality/backend_gate.sh >/dev/null; then
    fail "Backend quality gate does not invoke the internal evaluation gate"
  fi
  pass "Backend quality gate invokes the internal evaluation gate"

  if rg -n "from app\\.main import app" backend/tests --glob '!test_phase6_quality_gate.py' >/dev/null; then
    fail "At least one test still imports app.main directly"
  fi
  pass "No direct app.main imports remain in backend tests"

  echo "Phase 6 validation completed."
}

phase_7_checks() {
  echo "Running Phase 7 validation checks..."
  local py
  py="$(detect_python)"

  check_file_exists "README.md"
  check_file_exists "CONTRIBUTING.md"
  check_file_exists "docs/ARCHITECTURE.md"
  check_file_exists "docs/implementation_plan.md"
  check_file_exists "backend/tests/test_phase7_docs_alignment.py"

  if ! DEBUG=false ENABLE_DEMO_AUTH=true "${py}" -m pytest -c backend/pytest.ini --noconftest \
    backend/tests/test_phase7_docs_alignment.py \
    -q; then
    fail "Phase 7 docs alignment pytest checks failed"
  fi
  pass "Phase 7 docs alignment pytest checks passed"

  if rg -n "Next\\.js 14|npx tsc --noEmit|frontend/src/components/|frontend/src/lib/|npm run dev$" README.md CONTRIBUTING.md docs/ARCHITECTURE.md docs/implementation_plan.md docs/walkthrough.md >/dev/null; then
    fail "Legacy Next.js/frontend src references still present in canonical docs"
  fi
  pass "Canonical docs are aligned with static frontend architecture"

  echo "Phase 7 validation completed."
}

phase_8_checks() {
  echo "Running Phase 8 validation checks..."
  local py
  py="$(detect_python)"

  check_file_exists "docs/release-readiness.md"
  check_file_exists "scripts/quality/release_readiness.sh"
  check_file_exists "scripts/quality/migration_gate.sh"
  check_file_exists "scripts/quality/integration_gate.sh"
  check_file_exists "scripts/quality/security_gate.sh"
  check_file_exists "scripts/quality/staging_smoke.sh"
  check_file_exists "backend/scripts/staging_smoke.py"
  check_file_exists "scripts/ops/backup_postgres.sh"
  check_file_exists "scripts/ops/restore_postgres.sh"
  check_file_exists "scripts/ops/backup_object_storage.sh"
  check_file_exists "scripts/ops/backup_vector_graph.sh"
  check_file_exists "scripts/ops/backup_restore_drill.sh"
  check_file_exists "docker-compose.staging.yml"
  check_file_exists "backend/tests/test_phase8_release_readiness.py"
  check_file_exists "frontend/public/js/api.js"
  check_file_exists "backend/app/api/documents.py"

  "${py}" -m compileall backend/app >/dev/null
  pass "Python compile check passed for backend/app"

  if ! DEBUG=false ENABLE_DEMO_AUTH=true "${py}" -m pytest -c backend/pytest.ini --noconftest \
    backend/tests/test_phase8_release_readiness.py \
    -q; then
    fail "Phase 8 release-readiness pytest checks failed"
  fi
  pass "Phase 8 release-readiness pytest checks passed"

  if rg -n "hf\\.space" frontend/public/js/api.js >/dev/null; then
    fail "Frontend API client still contains hardcoded hf.space host"
  fi
  pass "Frontend API base is not hardcoded to hf.space"

  if rg -n "_DEBUG_LOG_PATH|/Users/" backend/app/api/documents.py >/dev/null; then
    fail "Documents API still contains local absolute debug log path artifacts"
  fi
  pass "Documents API has no local absolute debug log path artifacts"

  if ! bash scripts/quality/release_readiness.sh; then
    fail "Release-readiness orchestration script failed"
  fi
  pass "Release-readiness orchestration script passed"

  echo "Phase 8 validation completed."
}

case "${PHASE}" in
  1)
    phase_1_checks
    ;;
  2)
    phase_2_checks
    ;;
  3)
    phase_3_checks
    ;;
  4)
    phase_4_checks
    ;;
  5)
    phase_5_checks
    ;;
  6)
    phase_6_checks
    ;;
  7)
    phase_7_checks
    ;;
  8)
    phase_8_checks
    ;;
  *)
    echo "Phase ${PHASE} validation is not implemented yet."
    echo "Available: 1, 2, 3, 4, 5, 6, 7, 8"
    exit 2
    ;;
esac
