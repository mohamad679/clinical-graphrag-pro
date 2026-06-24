#!/usr/bin/env python3
"""Evaluate synthetic_retrieval_benchmark_v2 with real retrieval services."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import platform
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings
from app.services.bm25_index import BM25Index
from app.services.query_engine import QueryEngine
from app.services.vector_store import FAISSBackend
import app.services.query_engine as query_engine_module


DEFAULT_DATASET = BACKEND_DIR / "data" / "synthetic_retrieval_benchmark_v2.json"
SCHEMA_VERSION = "retrieval-benchmark-v2.1"
METHODS = {
    "dense": "dense",
    "sparse": "sparse",
    "hybrid_rrf": "hybrid",
    "hybrid_plus_rerank": "hybrid_rerank",
}
TOP_K = [1, 3, 5]
DEFAULT_RETRIEVAL_MODE = "hybrid_rrf"
REQUIRED_SUCCESS_GATES = {
    "duplicate_ratio_lte_0_05",
    "cross_tenant_leakage_count_eq_0",
    "default_mode_recall_at_5_gte_0_70",
    "answerable_queries_without_expected_evidence_in_top_5_rate_lte_0_20",
    "category_metrics_present",
    "dataset_version_present",
    "commit_hash_present",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(args: list[str]) -> str | None:
    try:
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = (len(ordered) - 1) * q
    low = math.floor(idx)
    high = math.ceil(idx)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - idx) + ordered[high] * (idx - low)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def required_gate_failures(success_gates: dict) -> list[str]:
    return [gate for gate in sorted(REQUIRED_SUCCESS_GATES) if not success_gates.get(gate, False)]


def validate_gate_payload(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures = required_gate_failures(payload.get("success_gates", {}))
    if failures:
        print(f"Required retrieval benchmark gates failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("Required retrieval benchmark gates passed.")
    if payload.get("success_gates", {}).get("rerank_latency_justified") is False:
        print("Reranker latency gate failed; informational only.")
    return 0


def ndcg(relevance: list[int], total_relevant: int, k: int = 5) -> float:
    dcg = sum(rel / math.log2(rank + 2) for rank, rel in enumerate(relevance[:k]))
    ideal = [1] * min(total_relevant, k)
    idcg = sum(rel / math.log2(rank + 2) for rank, rel in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def result_id(result) -> str:
    return getattr(result, "chunk_id", None) or result.get("chunk_id", "")


def result_score(result) -> float:
    return float(getattr(result, "score", None) if hasattr(result, "score") else result.get("score", 0.0) or 0.0)


def snapshot(results: list, metadata_by_chunk: dict[str, dict]) -> list[dict]:
    rows = []
    for rank, result in enumerate(results):
        chunk_id = result_id(result)
        meta = metadata_by_chunk.get(chunk_id, {})
        rows.append(
            {
                "rank": rank,
                "chunk_id": chunk_id,
                "document_id": getattr(result, "document_id", None) or result.get("document_id", ""),
                "document_name": getattr(result, "document_name", None) or result.get("document_name", ""),
                "score": result_score(result),
                "tenant_id": meta.get("tenant_id"),
                "patient_id": meta.get("patient_id"),
            }
        )
    return rows


def score_query(query: dict, ranked_ids: list[str], metadata_by_chunk: dict[str, dict]) -> dict:
    expected = set(query.get("expected_evidence_ids") or [])
    relevance = [1 if chunk_id in expected else 0 for chunk_id in ranked_ids]
    total_relevant = len(expected)
    answerable = total_relevant > 0
    first_hit = next((idx + 1 for idx, rel in enumerate(relevance) if rel), None)
    leakage = 0
    for chunk_id in ranked_ids:
        meta = metadata_by_chunk.get(chunk_id, {})
        if meta and meta.get("tenant_id") != query.get("tenant_id"):
            leakage += 1
    metrics = {
        "answerable": answerable,
        "cross_tenant_leakage_count": leakage,
        "zero_results": int(len(ranked_ids) == 0),
        "abstention_correct": None,
    }
    if query.get("abstention_expected"):
        metrics["abstention_correct"] = int(len(ranked_ids) == 0)
    if not answerable:
        for k in TOP_K:
            metrics[f"recall_at_{k}"] = None
        metrics.update({"precision_at_5": None, "mrr": None, "ndcg_at_5": None})
        return metrics
    for k in TOP_K:
        metrics[f"recall_at_{k}"] = sum(relevance[:k]) / total_relevant
    metrics["precision_at_5"] = sum(relevance[:5]) / 5
    metrics["mrr"] = 1.0 / first_hit if first_hit else 0.0
    metrics["ndcg_at_5"] = ndcg(relevance, total_relevant, 5)
    return metrics


def aggregate(records: list[dict]) -> dict:
    answerable = [record for record in records if record["metrics"]["answerable"]]
    abstention = [record for record in records if record["metrics"]["abstention_correct"] is not None]
    latencies = [record["latency_ms"] for record in records]
    def metric(name: str) -> float:
        return mean([record["metrics"][name] for record in answerable])
    return {
        "query_count": len(records),
        "answerable_query_count": len(answerable),
        "mean_latency_ms": mean(latencies),
        "latency_p50_ms": median(latencies) if latencies else 0.0,
        "latency_p95_ms": percentile(latencies, 0.95),
        "latency_p99_ms": percentile(latencies, 0.99),
        "mrr": metric("mrr") if answerable else 0.0,
        "precision_at_5": metric("precision_at_5") if answerable else 0.0,
        "recall_at_1": metric("recall_at_1") if answerable else 0.0,
        "recall_at_3": metric("recall_at_3") if answerable else 0.0,
        "recall_at_5": metric("recall_at_5") if answerable else 0.0,
        "ndcg_at_5": metric("ndcg_at_5") if answerable else 0.0,
        "zero_result_rate": mean([record["metrics"]["zero_results"] for record in records]),
        "abstention_accuracy": mean([record["metrics"]["abstention_correct"] for record in abstention]) if abstention else None,
        "cross_tenant_leakage_count": sum(record["metrics"]["cross_tenant_leakage_count"] for record in records),
        "empty_index_failures": sum(record.get("empty_index_failure", 0) for record in records),
        "authorization_filter_rejection_count": sum(record.get("authorization_filter_rejection_count", 0) for record in records),
    }


def render_markdown(payload: dict) -> str:
    lines = [
        f"# Retrieval Benchmark v2 Report - {payload['metadata']['timestamp']}",
        "",
        "Synthetic retrieval regression benchmark only. This is not clinical validation or SOTA evidence.",
        "",
        "## Dataset",
        "",
        f"- Version: `{payload['dataset']['version']}`",
        f"- Queries: {payload['dataset']['query_count']}",
        f"- Corpus chunks: {payload['corpus_statistics']['chunk_count']}",
        f"- Duplicate ratio: {payload['dataset']['summary']['duplicate_ratio']:.4f}",
        f"- Seed: {payload['metadata']['seed']}",
        "",
        "## Overall Metrics",
        "",
        "| Mode | MRR | R@1 | R@3 | R@5 | P@5 | nDCG@5 | Abstention acc. | Leakage | Mean ms | p50 | p95 | p99 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, metrics in payload["results"].items():
        abst = metrics["abstention_accuracy"]
        abst_text = "N/A" if abst is None else f"{abst:.4f}"
        lines.append(
            f"| {mode} | {metrics['mrr']:.4f} | {metrics['recall_at_1']:.4f} | {metrics['recall_at_3']:.4f} | "
            f"{metrics['recall_at_5']:.4f} | {metrics['precision_at_5']:.4f} | {metrics['ndcg_at_5']:.4f} | "
            f"{abst_text} | {metrics['cross_tenant_leakage_count']} | {metrics['mean_latency_ms']:.2f} | "
            f"{metrics['latency_p50_ms']:.2f} | {metrics['latency_p95_ms']:.2f} | {metrics['latency_p99_ms']:.2f} |"
        )
    lines.extend(["", "## Category Recall@5", "", "| Category | Dense | Sparse | Hybrid | Rerank |", "| --- | ---: | ---: | ---: | ---: |"])
    categories = sorted(payload["category_results"]["dense"])
    for category in categories:
        lines.append(
            f"| {category} | {payload['category_results']['dense'][category]['recall_at_5']:.4f} | "
            f"{payload['category_results']['sparse'][category]['recall_at_5']:.4f} | "
            f"{payload['category_results']['hybrid_rrf'][category]['recall_at_5']:.4f} | "
            f"{payload['category_results']['hybrid_plus_rerank'][category]['recall_at_5']:.4f} |"
        )
    lines.extend(["", "## Success Gates", ""])
    for gate, status in payload["success_gates"].items():
        lines.append(f"- {gate}: `{status}`")
    lines.extend(
        [
            "",
            f"- default_retrieval_mode: `{payload['quality_gates']['default_retrieval_mode']}`",
            f"- required_gate_status: `{payload['quality_gates']['required_gate_status']}`",
            f"- required_gate_failures: `{', '.join(payload['quality_gates']['required_gate_failures']) or 'none'}`",
            "- reranker_latency_justified: "
            f"`{payload['success_gates'].get('rerank_latency_justified')}` "
            "(informational only)",
        ]
    )
    lines.append("")
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> None:
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    settings = get_settings()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or (REPO_ROOT / "results" / f"retrieval_benchmark_v2_{timestamp}.json")

    with tempfile.TemporaryDirectory(prefix="clinical-retrieval-v2-") as temp_dir:
        patches = [patch.object(settings, "vector_store_dir", Path(temp_dir) / "vector_store")]
        if args.embedding_model:
            patches.append(patch.object(settings, "embedding_model", args.embedding_model))
        if args.embedding_dim:
            patches.append(patch.object(settings, "embedding_dim", args.embedding_dim))
        for active in patches:
            active.start()
        try:
            vector = FAISSBackend()
            sparse = BM25Index(use_database=False)
            embedder = vector._get_embedder()
            effective_dim = (
                int(embedder.get_sentence_embedding_dimension())
                if hasattr(embedder, "get_sentence_embedding_dimension")
                else int(settings.embedding_dim)
            )
            with patch.object(settings, "embedding_dim", effective_dim):
                for chunk in dataset["corpus"]:
                    metadata = dict(chunk.get("metadata") or {})
                    payload = [{"chunk_id": chunk["chunk_id"], "chunk_index": chunk.get("chunk_index", 0), "text": chunk["text"], "metadata": metadata}]
                    vector.add_documents(chunk["document_id"], chunk["document_name"], chunk["text"], chunks=payload, metadata=metadata)
                    sparse.add_document(payload, chunk["document_id"], chunk["document_name"], user_id=metadata.get("user_id"), metadata=metadata)

            metadata_by_chunk = {chunk["chunk_id"]: dict(chunk.get("metadata") or {}) for chunk in dataset["corpus"]}
            traces: list[dict] = []
            records_by_mode: dict[str, list[dict]] = {mode: [] for mode in METHODS}

            for mode, engine_mode in METHODS.items():
                for query in dataset["queries"]:
                    filters = {"tenant_id": query["tenant_id"], "patient_id": query["patient_id"], "user_id": query["user_id"]}
                    started = time.perf_counter()
                    empty_index_failure = 0
                    auth_rejections = 0
                    trace_info = None
                    try:
                        if mode == "dense":
                            retrieved = vector.search(query["query_text"], top_k=5, filters=filters)
                            candidates = snapshot(retrieved, metadata_by_chunk)
                        elif mode == "sparse":
                            if int(sparse.get_stats().get("total_documents") or 0) == 0:
                                raise RuntimeError("BM25 sparse index is empty while sparse retrieval is enabled.")
                            retrieved = sparse.search(query["query_text"], top_k=5, filters=filters)
                            candidates = snapshot(retrieved, metadata_by_chunk)
                        else:
                            with patch.object(query_engine_module, "vector_store_service", vector), patch.object(query_engine_module, "bm25_index", sparse):
                                response = await QueryEngine().query(
                                    query["query_text"],
                                    top_k=5,
                                    mode=engine_mode,
                                    expand_query=False,
                                    filters=filters,
                                    trace=True,
                                )
                            retrieved = response.results
                            candidates = snapshot(retrieved, metadata_by_chunk)
                            trace_info = response.trace_info
                    except Exception as exc:
                        retrieved = []
                        candidates = []
                        trace_info = {"exception": f"{exc.__class__.__name__}: {exc}"}
                        if "BM25 sparse index is empty" in str(exc):
                            empty_index_failure = 1
                    latency_ms = (time.perf_counter() - started) * 1000
                    ranked_ids = [candidate["chunk_id"] for candidate in candidates]
                    if not ranked_ids:
                        probe = sparse.search(query["query_text"], top_k=1, filters=None) if mode == "sparse" else vector.search(query["query_text"], top_k=1, filters=None)
                        auth_rejections = int(bool(probe))
                    metrics = score_query(query, ranked_ids, metadata_by_chunk)
                    record = {
                        "query_id": query["query_id"],
                        "category": query["category"],
                        "latency_ms": latency_ms,
                        "ranked_chunk_ids": ranked_ids,
                        "metrics": metrics,
                        "empty_index_failure": empty_index_failure,
                        "authorization_filter_rejection_count": auth_rejections,
                    }
                    records_by_mode[mode].append(record)
                    traces.append(
                        {
                            "query_id": query["query_id"],
                            "mode": mode,
                            "filters": filters,
                            "candidates": candidates,
                            "latency_ms": latency_ms,
                            "trace_info": trace_info,
                        }
                    )

            category_results: dict[str, dict] = {}
            for mode, records in records_by_mode.items():
                category_results[mode] = {}
                grouped: dict[str, list[dict]] = defaultdict(list)
                for record in records:
                    grouped[record["category"]].append(record)
                for category, category_records in grouped.items():
                    category_results[mode][category] = aggregate(category_records)

            status_short = git_value(["status", "--short"]) or ""
            commit_hash = git_value(["rev-parse", "HEAD"])
            results = {mode: aggregate(records) for mode, records in records_by_mode.items()}
            default_records = records_by_mode[DEFAULT_RETRIEVAL_MODE]
            default_answerable = [record for record in default_records if record["metrics"]["answerable"]]
            answerable_without_expected_top5_rate = mean(
                [int(record["metrics"]["recall_at_5"] == 0.0) for record in default_answerable]
            )
            category_metrics_present = bool(category_results) and all(
                bool(category_results.get(mode)) for mode in METHODS
            )
            total_cross_tenant_leakage_count = sum(
                metrics["cross_tenant_leakage_count"] for metrics in results.values()
            )
            success_gates = {
                "duplicate_ratio_lte_0_05": dataset["summary"]["duplicate_ratio"] <= 0.05,
                "sparse_index_non_empty": int(sparse.get_stats().get("total_documents") or 0) > 0,
                "cross_tenant_leakage_zero_all_modes": all(metrics["cross_tenant_leakage_count"] == 0 for metrics in results.values()),
                "cross_tenant_leakage_count_eq_0": total_cross_tenant_leakage_count == 0,
                "default_mode_recall_at_5_gte_0_70": results[DEFAULT_RETRIEVAL_MODE]["recall_at_5"] >= 0.70,
                "answerable_queries_without_expected_evidence_in_top_5_rate_lte_0_20": (
                    answerable_without_expected_top5_rate <= 0.20
                ),
                "category_metrics_present": category_metrics_present,
                "dataset_version_present": bool(dataset.get("dataset_version")),
                "commit_hash_present": bool(commit_hash),
                "hybrid_claim_supported": results["hybrid_rrf"]["recall_at_5"] > results["dense"]["recall_at_5"],
                "rerank_latency_justified": (
                    results["hybrid_plus_rerank"]["recall_at_5"] > results["hybrid_rrf"]["recall_at_5"]
                    and results["hybrid_plus_rerank"]["mean_latency_ms"] <= results["hybrid_rrf"]["mean_latency_ms"] * 2
                ),
            }
            required_gate_failure_names = required_gate_failures(success_gates)
            payload = {
                "artifact_schema_version": SCHEMA_VERSION,
                "artifact_type": "synthetic_retrieval_benchmark",
                "metadata": {
                    "timestamp": timestamp,
                    "seed": dataset["seed"],
                    "benchmark_category": "retrieval-quality benchmark",
                    "note": "Synthetic retrieval regression benchmark; not clinical validation or SOTA clinical performance.",
                },
                "code": {
                    "git_commit": commit_hash,
                    "git_branch": git_value(["branch", "--show-current"]),
                    "working_tree_status_sha256_16": hashlib.sha256(status_short.encode("utf-8")).hexdigest()[:16],
                    "working_tree_dirty_entries": len([line for line in status_short.splitlines() if line.strip()]),
                },
                "dataset": {
                    "path": str(args.dataset),
                    "sha256": sha256_file(args.dataset),
                    "version": dataset["dataset_version"],
                    "generator_version": dataset["generator_version"],
                    "query_count": len(dataset["queries"]),
                    "summary": dataset["summary"],
                },
                "configuration": {
                    "embedding_model": settings.embedding_model,
                    "embedding_dimension": effective_dim,
                    "chunking": "predefined stable chunks from dataset",
                    "top_k": 5,
                    "sparse_evaluation_backend": "rank_bm25.BM25Okapi" if sparse._index is not None else "token-overlap fallback",
                    "database_runtime_sparse_backend": "PostgreSQL Full-Text Search",
                    "postgres_runtime_rank_function": "ts_rank_cd",
                    "query_expansion": False,
                    "default_retrieval_mode": DEFAULT_RETRIEVAL_MODE,
                },
                "corpus_statistics": {
                    "chunk_count": len(dataset["corpus"]),
                    "bm25_stats": sparse.get_stats(),
                    "category_counts": dict(Counter(chunk.get("metadata", {}).get("category") for chunk in dataset["corpus"])),
                },
                "runtime": {"python": sys.version, "platform": platform.platform(), "executable": sys.executable},
                "backend_mode": {"dense_backend": "faiss", "sparse_backend": "rank_bm25.BM25Okapi", "hybrid_fusion": "RRF", "reranker": "optional cross-encoder with explicit fallback"},
                "results": results,
                "category_results": category_results,
                "query_records": records_by_mode,
                "retriever_traces": traces,
                "success_gates": success_gates,
                "quality_gates": {
                    "required_gates": sorted(REQUIRED_SUCCESS_GATES),
                    "informational_gates": ["sparse_index_non_empty", "hybrid_claim_supported", "rerank_latency_justified"],
                    "required_gate_status": "passed" if not required_gate_failure_names else "failed",
                    "required_gate_failures": required_gate_failure_names,
                    "default_retrieval_mode": DEFAULT_RETRIEVAL_MODE,
                    "default_mode_recall_at_5": results[DEFAULT_RETRIEVAL_MODE]["recall_at_5"],
                    "answerable_queries_without_expected_evidence_in_top_5_rate": answerable_without_expected_top5_rate,
                    "cross_tenant_leakage_count": total_cross_tenant_leakage_count,
                },
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            markdown = args.markdown_output or output.with_suffix(".md")
            markdown.write_text(render_markdown(payload), encoding="utf-8")
            print(render_markdown(payload))
            print(f"Saved JSON benchmark artifact to {output}")
            print(f"Saved Markdown benchmark report to {markdown}")
            if required_gate_failure_names:
                print(f"Required retrieval benchmark gates failed: {', '.join(required_gate_failure_names)}", file=sys.stderr)
                raise SystemExit(1)
        finally:
            for active in reversed(patches):
                active.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval benchmark v2.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--embedding-dim", type=int, default=None)
    parser.add_argument("--validate-gates-only", type=Path, default=None)
    args = parser.parse_args()
    if args.validate_gates_only:
        raise SystemExit(validate_gate_payload(args.validate_gates_only))
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
