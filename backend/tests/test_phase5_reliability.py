"""
Phase 5 reliability checks for config and tooling alignment.
Run with: pytest --noconftest backend/tests/test_phase5_reliability.py -q
"""

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_makefile_uses_python3_or_venv_python():
    makefile = (_repo_root() / "Makefile").read_text(encoding="utf-8")
    assert "python -m pytest" not in makefile
    assert "BACKEND_PY := " in makefile
    assert "python3" in makefile


def test_requirements_include_lint_and_cov_tools():
    req = (_repo_root() / "backend/requirements.txt").read_text(encoding="utf-8")
    assert "ruff==" in req
    assert "pytest-cov==" in req


def test_dev_compose_does_not_reference_missing_frontend_target():
    dev_compose = (_repo_root() / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "target: deps" not in dev_compose
    assert "npm run dev" not in dev_compose


def test_prod_compose_web_healthcheck_matches_frontend_port():
    compose = (_repo_root() / "docker-compose.yml").read_text(encoding="utf-8")
    assert "http://127.0.0.1:3000/" in compose


def test_sqlite_runtime_uses_busy_timeout_and_wal():
    database_py = (_repo_root() / "backend/app/core/database.py").read_text(encoding="utf-8")
    assert '"timeout": 30' in database_py
    assert "PRAGMA busy_timeout=30000" in database_py
    assert "PRAGMA journal_mode=WAL" in database_py


def test_entrypoint_forces_single_worker_for_sqlite():
    entrypoint = (_repo_root() / "backend/docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "SQLite database detected; forcing a single uvicorn worker" in entrypoint
    assert "workers=1" in entrypoint
