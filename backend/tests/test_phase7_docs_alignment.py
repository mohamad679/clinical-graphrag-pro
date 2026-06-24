"""
Phase 7 docs alignment checks.
Run with: pytest --noconftest backend/tests/test_phase7_docs_alignment.py -q
"""

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_readme_does_not_claim_nextjs_runtime():
    readme = (_repo_root() / "README.md").read_text(encoding="utf-8").lower()
    assert "next.js 14" not in readme
    assert "npm run dev" not in readme


def test_contributing_does_not_reference_frontend_src_tree():
    doc = (_repo_root() / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "frontend/src/" not in doc
    assert "npx tsc --noEmit" not in doc


def test_architecture_matches_static_frontend():
    arch = (_repo_root() / "docs/ARCHITECTURE.md").read_text(encoding="utf-8").lower()
    assert "static" in arch
    assert "web components" in arch
    assert "no next.js/typescript runtime" in arch
