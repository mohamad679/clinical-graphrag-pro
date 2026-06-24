"""
Phase 8 release-readiness checks.
Run with: pytest --noconftest backend/tests/test_phase8_release_readiness.py -q
"""

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_frontend_api_base_is_not_hardcoded_external():
    content = (_repo_root() / "frontend/public/js/api.js").read_text(encoding="utf-8")
    assert "hf.space" not in content
    assert "resolveApiBase" in content


def test_documents_api_has_no_local_absolute_debug_log_path():
    content = (_repo_root() / "backend/app/api/documents.py").read_text(encoding="utf-8")
    assert "_DEBUG_LOG_PATH" not in content
    assert "/Users/" not in content


def test_release_readiness_assets_exist():
    assert (_repo_root() / "docs/release-readiness.md").exists()
    assert (_repo_root() / "scripts/quality/release_readiness.sh").exists()
    assert (_repo_root() / "scripts/quality/migration_gate.sh").exists()
    assert (_repo_root() / "scripts/quality/integration_gate.sh").exists()
    assert (_repo_root() / "scripts/quality/security_gate.sh").exists()
    assert (_repo_root() / "scripts/quality/staging_smoke.sh").exists()
    assert (_repo_root() / "scripts/quality/fresh_env_verify.sh").exists()
    assert (_repo_root() / "backend/scripts/staging_smoke.py").exists()
    assert (_repo_root() / "scripts/ops/backup_postgres.sh").exists()
    assert (_repo_root() / "scripts/ops/restore_postgres.sh").exists()
    assert (_repo_root() / "scripts/ops/backup_object_storage.sh").exists()
    assert (_repo_root() / "scripts/ops/backup_vector_graph.sh").exists()
    assert (_repo_root() / "scripts/ops/backup_restore_drill.sh").exists()
    assert (_repo_root() / "docker-compose.staging.yml").exists()
    assert (_repo_root() / "MODEL_CARD.md").exists()
    assert (_repo_root() / "THREAT_MODEL.md").exists()
    assert (_repo_root() / "EVALUATION_STATUS.md").exists()
    assert (_repo_root() / "docs/HARDENING_VERIFICATION_REPORT.md").exists()


def test_release_workflow_references_gates():
    workflow = (_repo_root() / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "scripts/quality/migration_gate.sh" in workflow
    assert "scripts/quality/integration_gate.sh" in workflow
    assert "scripts/quality/security_gate.sh" in workflow
    assert "test_final_hardening_gate.py" in workflow
    assert "test_retrieval_regression.py" in workflow
    assert "scripts/quality/fresh_env_verify.sh" in workflow
    assert "scripts/quality/release_readiness.sh" in workflow


def test_release_readiness_doc_mentions_backup_staging_and_rollback():
    content = (_repo_root() / "docs/release-readiness.md").read_text(encoding="utf-8").lower()
    assert "backup" in content
    assert "staging" in content
    assert "rollback" in content
