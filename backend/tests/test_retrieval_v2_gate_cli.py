from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REQUIRED_PASSING_GATES = {
    "duplicate_ratio_lte_0_05": True,
    "cross_tenant_leakage_count_eq_0": True,
    "default_mode_recall_at_5_gte_0_70": True,
    "answerable_queries_without_expected_evidence_in_top_5_rate_lte_0_20": True,
    "category_metrics_present": True,
    "dataset_version_present": True,
    "commit_hash_present": True,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_gate_payload(tmp_path: Path, gates: dict) -> Path:
    path = tmp_path / "gate-payload.json"
    path.write_text(json.dumps({"success_gates": gates}), encoding="utf-8")
    return path


def _run_gate_validation(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_repo_root() / "scripts" / "evaluate_retrieval_v2.py"), "--validate-gates-only", str(path)],
        cwd=_repo_root(),
        text=True,
        capture_output=True,
        check=False,
    )


def test_retrieval_v2_gate_validation_exits_nonzero_for_required_failure(tmp_path):
    payload = _write_gate_payload(
        tmp_path,
        {**REQUIRED_PASSING_GATES, "default_mode_recall_at_5_gte_0_70": False},
    )

    result = _run_gate_validation(payload)

    assert result.returncode == 1
    assert "default_mode_recall_at_5_gte_0_70" in result.stderr


def test_retrieval_v2_gate_validation_exits_zero_for_required_success(tmp_path):
    payload = _write_gate_payload(tmp_path, {**REQUIRED_PASSING_GATES, "rerank_latency_justified": True})

    result = _run_gate_validation(payload)

    assert result.returncode == 0
    assert "Required retrieval benchmark gates passed" in result.stdout


def test_retrieval_v2_reranker_latency_warning_alone_does_not_fail(tmp_path):
    payload = _write_gate_payload(tmp_path, {**REQUIRED_PASSING_GATES, "rerank_latency_justified": False})

    result = _run_gate_validation(payload)

    assert result.returncode == 0
    assert "informational only" in result.stdout
