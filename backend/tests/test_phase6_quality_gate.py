"""
Phase 6 quality-gate checks.
Run with: pytest --noconftest backend/tests/test_phase6_quality_gate.py -q
"""

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_backend_quality_gate_script_exists():
    gate = _repo_root() / "scripts/quality/backend_gate.sh"
    assert gate.exists()
    assert gate.stat().st_size > 0


def test_internal_evaluation_gate_script_exists():
    gate = _repo_root() / "scripts/quality/evaluation_gate.sh"
    assert gate.exists()
    assert gate.stat().st_size > 0


def test_backend_quality_gate_invokes_internal_evaluation_gate():
    content = (_repo_root() / "scripts/quality/backend_gate.sh").read_text(encoding="utf-8")
    assert "evaluation_gate.sh" in content


def test_no_tests_import_full_app_main():
    tests_dir = _repo_root() / "backend/tests"
    offenders = []
    forbidden = "from app.main import app"
    for path in tests_dir.glob("test_*.py"):
        if path.name == "test_phase6_quality_gate.py":
            continue
        content = path.read_text(encoding="utf-8")
        if forbidden in content:
            offenders.append(str(path))
    assert offenders == []


def test_phase_check_script_supports_phase_6():
    phase_check = (_repo_root() / "scripts/quality/phase_check.sh").read_text(encoding="utf-8")
    assert "phase_6_checks" in phase_check
    assert "  6)" in phase_check
