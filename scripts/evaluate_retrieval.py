#!/usr/bin/env python3
"""
Custom Retrieval Evaluator for Clinical GraphRAG Pro.
Calculates Recall@k, Precision@k, MRR, nDCG, failure counts, candidate
flow diagnostics, and latency profiles. This is a synthetic regression
benchmark harness, not clinical validation.
"""

import sys
from pathlib import Path
import json
import time
import math
import tempfile
import hashlib
import platform
import subprocess
from datetime import datetime, timezone
from statistics import median
from unittest.mock import patch

# Setup paths
SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Import settings and services
from app.core.config import get_settings
from app.services.bm25_index import BM25Index
from app.services.vector_store import FAISSBackend
from app.services.query_engine import QueryEngine
import app.services.query_engine as query_engine_module

DATASET_PATH = BACKEND_DIR / "data" / "golden_evaluation_dataset.jsonl"
TOP_K_LIST = [1, 3, 5]
METHODS = ["FAISS Only", "BM25 Only", "Hybrid (FAISS + BM25 + RRF)", "Hybrid + Rerank"]
SPARSE_METHODS = {"BM25 Only", "Hybrid (FAISS + BM25 + RRF)", "Hybrid + Rerank"}
HYBRID_METHODS = {"Hybrid (FAISS + BM25 + RRF)", "Hybrid + Rerank"}
ARTIFACT_SCHEMA_VERSION = "retrieval-benchmark-v2"


def load_evaluation_cases(dataset_path: Path) -> tuple[list[dict], int]:
    """Load either the legacy golden set or the synthetic benchmark schema."""
    cases = []
    skipped = 0
    with open(dataset_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if not line.strip():
                continue
            data = json.loads(line)

            if "evidence_chunks" in data:
                evidence_chunks = data.get("evidence_chunks") or []
                required_chunk_ids = set(data.get("required_evidence_chunks") or [])
                if not data.get("should_answer", True) or not required_chunk_ids:
                    skipped += 1
                    continue
                contexts = [chunk.get("text", "") for chunk in evidence_chunks if chunk.get("text")]
                relevant_indexes = [
                    index
                    for index, chunk in enumerate(evidence_chunks)
                    if chunk.get("chunk_id") in required_chunk_ids and chunk.get("text")
                ]
                cases.append({
                    "case_index": idx,
                    "case_id": data.get("id", f"case-{idx}"),
                    "question": data["question"],
                    "ground_truth": data.get("expected_answer", ""),
                    "contexts": contexts,
                    "relevant_context_indexes": relevant_indexes,
                })
            else:
                contexts = data.get("context") or data.get("contexts") or []
                if isinstance(contexts, str):
                    contexts = [contexts]
                cases.append({
                    "case_index": idx,
                    "case_id": data.get("id", f"case-{idx}"),
                    "question": data["question"],
                    "ground_truth": data["ground_truth"],
                    "contexts": contexts,
                    "relevant_context_indexes": list(range(len(contexts))),
                })
    return cases, skipped

def get_percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_val = sorted(values)
    idx = (len(sorted_val) - 1) * q
    low = math.floor(idx)
    high = math.ceil(idx)
    if low == high:
        return sorted_val[low]
    return sorted_val[low] * (high - idx) + sorted_val[high] * (idx - low)

def calculate_ndcg(retrieved_relevance: list[int], ideal_relevance: list[int], k: int) -> float:
    dcg = 0.0
    for i in range(min(k, len(retrieved_relevance))):
        rel = retrieved_relevance[i]
        dcg += rel / math.log2(i + 2)
        
    idcg = 0.0
    sorted_ideal = sorted(ideal_relevance, reverse=True)
    for i in range(min(k, len(sorted_ideal))):
        rel = sorted_ideal[i]
        idcg += rel / math.log2(i + 2)
        
    if idcg == 0.0:
        return 0.0
    return dcg / idcg

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

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def validate_artifact_payload(payload: dict) -> None:
    """Validate the benchmark artifact contract before writing it."""
    required_top_level = {
        "artifact_schema_version",
        "artifact_type",
        "metadata",
        "dataset",
        "code",
        "configuration",
        "corpus_statistics",
        "runtime",
        "backend_mode",
        "results",
    }
    missing_top = sorted(required_top_level - set(payload))
    if missing_top:
        raise ValueError(f"Benchmark artifact missing top-level fields: {missing_top}")

    required_metadata = {"timestamp", "seed", "benchmark_category", "note"}
    missing_metadata = sorted(required_metadata - set(payload["metadata"]))
    if missing_metadata:
        raise ValueError(f"Benchmark artifact missing metadata fields: {missing_metadata}")

    required_result_fields = {
        "latency_mean",
        "latency_p50",
        "latency_p95",
        "latency_p99",
        "mrr",
        "precision_at_1",
        "recall_at_1",
        "recall_at_3",
        "recall_at_5",
        "ndcg_at_5",
        "zero_result_rate",
        "failure_counts",
        "candidate_counts",
    }
    required_failure_fields = {
        "no_results",
        "no_relevant_at_5",
        "exceptions",
        "empty_index_failures",
        "authorization_filter_rejection_count",
    }
    for method in METHODS:
        if method not in payload["results"]:
            raise ValueError(f"Benchmark artifact missing method results: {method}")
        method_payload = payload["results"][method]
        missing_method = sorted(required_result_fields - set(method_payload))
        if missing_method:
            raise ValueError(f"Benchmark method '{method}' missing fields: {missing_method}")
        missing_failures = sorted(required_failure_fields - set(method_payload["failure_counts"]))
        if missing_failures:
            raise ValueError(f"Benchmark method '{method}' missing failure fields: {missing_failures}")

def render_markdown_summary(payload: dict) -> str:
    """Render a human-readable report from a validated JSON payload."""
    validate_artifact_payload(payload)
    timestamp = payload["metadata"]["timestamp"]
    dataset = payload["dataset"]
    code = payload["code"]
    config = payload["configuration"]
    corpus = payload["corpus_statistics"]
    lines = [
        f"# Retrieval Benchmark Report - {timestamp}",
        "",
        "This is a synthetic retrieval-quality regression benchmark. It is not clinical validation,",
        "not a deployment safety claim, and not evidence of SOTA clinical performance.",
        "",
        "## Run Metadata",
        "",
        f"- Artifact schema: `{payload['artifact_schema_version']}`",
        f"- Benchmark category: `{payload['metadata']['benchmark_category']}`",
        f"- Seed: `{payload['metadata']['seed']}`",
        f"- Dataset: `{dataset['path']}`",
        f"- Dataset SHA-256: `{dataset['sha256']}`",
        f"- Query count: {dataset['query_count']}",
        f"- Skipped abstention-only cases: {dataset['skipped_abstention_only_cases']}",
        f"- Git commit: `{code.get('git_commit')}`",
        f"- Git branch: `{code.get('git_branch')}`",
        f"- Working-tree status SHA-16: `{code.get('working_tree_status_sha256_16')}`",
        f"- Backend mode: `{payload['backend_mode']['mode']}`",
        f"- Vector backend: `{payload['backend_mode']['dense_backend']}`",
        f"- Sparse backend: `{payload['backend_mode']['sparse_backend']}`",
        f"- Embedding model: `{config['embedding_model']}`",
        f"- Corpus chunks: {corpus['chunk_count']}",
        f"- BM25 token count: {corpus['bm25_stats'].get('token_count', 0)}",
        f"- BM25 vocabulary size: {corpus['bm25_stats'].get('vocabulary_size', 0)}",
        "",
        "## Metrics",
        "",
        "| Method | MRR | P@1 | R@1 | R@3 | R@5 | NDCG@5 | Zero-result rate | Empty-index failures | Auth-filter rejections | p50 ms | p95 ms | p99 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method in METHODS:
        metrics = payload["results"][method]
        failures = metrics["failure_counts"]
        lines.append(
            f"| {method} | {metrics['mrr']:.4f} | {metrics['precision_at_1']:.4f} | "
            f"{metrics['recall_at_1']:.4f} | {metrics['recall_at_3']:.4f} | "
            f"{metrics['recall_at_5']:.4f} | {metrics['ndcg_at_5']:.4f} | "
            f"{metrics['zero_result_rate']:.4f} | {failures['empty_index_failures']} | "
            f"{failures['authorization_filter_rejection_count']} | {metrics['latency_p50']:.2f} | "
            f"{metrics['latency_p95']:.2f} | {metrics['latency_p99']:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Candidate Flow",
            "",
            "| Method | Dense mean | Sparse mean | Merged mean | Reranked queries |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for method in METHODS:
        counts = payload["results"][method]["candidate_counts"]
        lines.append(
            f"| {method} | {counts['dense_mean']:.2f} | {counts['sparse_mean']:.2f} | "
            f"{counts['merged_mean']:.2f} | {counts['reranked_query_count']} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation Guardrail",
            "",
            "Only claim improvement when the measured metrics above improve. If hybrid or reranked",
            "retrieval matches dense retrieval while adding latency, report that directly.",
            "",
        ]
    )
    return "\n".join(lines)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality.")
    parser.add_argument("--tenant-id", default="demo-tenant", help="Tenant ID for evaluation isolation")
    parser.add_argument("--patient-id", default="pat-100", help="Patient ID for evaluation isolation")
    parser.add_argument("--user-id", default="user-123", help="User ID for evaluation isolation")
    parser.add_argument("--allow-unfiltered-demo", action="store_true", help="Allow unfiltered query searches")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH, help="Evaluation JSONL dataset path")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON path. Defaults to timestamped results artifact.")
    parser.add_argument("--markdown-output", type=Path, default=None, help="Output Markdown path. Defaults to the JSON path with .md suffix.")
    parser.add_argument("--no-markdown", action="store_true", help="Do not generate a Markdown report.")
    parser.add_argument("--seed", type=int, default=20260605, help="Deterministic seed recorded in the artifact.")
    args = parser.parse_args()

    print("==================================================")
    print("Running Custom Retrieval Quality Evaluation...")
    print(f"Isolation Context: tenant_id={args.tenant_id}, patient_id={args.patient_id}, user_id={args.user_id}, allow_unfiltered={args.allow_unfiltered_demo}")
    print("==================================================")
    
    if not args.dataset.exists():
        print(f"Error: Evaluation dataset not found at {args.dataset}")
        sys.exit(1)

    cases, skipped = load_evaluation_cases(args.dataset)
    print(f"Loaded {len(cases)} retrieval-evaluable cases from {args.dataset}.")
    if skipped:
        print(f"Skipped {skipped} abstention-only cases with no required retrieval target.")

    settings = get_settings()
    
    # Run evaluation inside a temp FAISS backend environment
    with tempfile.TemporaryDirectory(prefix="clinical-retrieval-eval-") as temp_dir:
        temp_store_path = Path(temp_dir) / "vector_store"
        temp_store_path.mkdir()
        
        with patch.object(settings, "vector_store_dir", temp_store_path):
            vector_backend = FAISSBackend()
            bm25_backend = BM25Index(use_database=False)
            
            # Setup base model to find dimensions
            embedder = vector_backend._get_embedder()
            eff_dim = int(embedder.get_sentence_embedding_dimension())
            
            # Index contexts with unique document IDs
            with patch.object(settings, "embedding_dim", eff_dim):
                for case in cases:
                    for c_idx, ctx_text in enumerate(case["contexts"]):
                        # Unique identifier for the context document
                        doc_id = f"case-{case['case_index']}-ctx-{c_idx}"
                        doc_name = f"case_{case['case_index']}_ctx_{c_idx}.txt"
                        
                        chunks = vector_backend.chunk_text(ctx_text, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
                        payloads = []
                        for index, chunk in enumerate(chunks):
                            payloads.append({
                                "chunk_id": chunk["chunk_id"],
                                "chunk_index": index,
                                "text": chunk["text"]
                            })
                        
                        vector_backend.add_documents(
                            document_id=doc_id,
                            document_name=doc_name,
                            text=ctx_text,
                            chunks=payloads,
                            metadata={
                                "tenant_id": args.tenant_id,
                                "patient_id": args.patient_id,
                                "user_id": args.user_id,
                            }
                        )
                        bm25_backend.add_document(
                            payloads,
                            doc_id,
                            doc_name,
                            user_id=args.user_id,
                            metadata={
                                "tenant_id": args.tenant_id,
                                "patient_id": args.patient_id,
                                "user_id": args.user_id,
                            },
                        )

            results_by_method = {}
            bm25_stats = bm25_backend.get_stats()
            vector_stats = vector_backend.get_stats()
            
            for method in METHODS:
                latencies = []
                recalls = {k: [] for k in TOP_K_LIST}
                precisions = {k: [] for k in TOP_K_LIST}
                mrrs = []
                ndcgs = {k: [] for k in TOP_K_LIST}
                failure_counts = {
                    "no_results": 0,
                    "no_relevant_at_5": 0,
                    "exceptions": 0,
                    "empty_index_failures": 0,
                    "authorization_filter_rejection_count": 0,
                }
                dense_counts = []
                sparse_counts = []
                merged_counts = []
                reranked_count = 0
                
                for case in cases:
                    expected_doc_names = {
                        f"case_{case['case_index']}_ctx_{context_index}.txt"
                        for context_index in case["relevant_context_indexes"]
                    }
                    query = case["question"]
                    
                    filters = {
                        "tenant_id": args.tenant_id,
                        "patient_id": args.patient_id,
                        "user_id": args.user_id,
                    }
                    
                    start_time = time.perf_counter()
                    # Perform retrieval
                    try:
                        if method in SPARSE_METHODS and int(bm25_stats.get("total_documents") or 0) == 0:
                            raise RuntimeError("BM25 sparse index is empty while sparse retrieval is enabled.")

                        if method == "FAISS Only":
                            retrieved = vector_backend.search(query, top_k=5, filters=filters)
                            retrieved_docs = [r.document_name for r in retrieved]
                            dense_counts.append(len(retrieved))
                        elif method == "BM25 Only":
                            retrieved = bm25_backend.search(query, top_k=5, user_id=args.user_id, filters=filters)
                            retrieved_docs = [r.get("document_name") for r in retrieved]
                            sparse_counts.append(len(retrieved))
                        else:
                            # Hybrid
                            with patch.object(query_engine_module, "vector_store_service", vector_backend):
                                with patch.object(query_engine_module, "bm25_index", bm25_backend):
                                    engine = QueryEngine()
                                    import asyncio
                                    loop = asyncio.new_event_loop()
                                    response = loop.run_until_complete(engine.query(
                                        query,
                                        top_k=5,
                                        mode="hybrid_rerank" if method == "Hybrid + Rerank" else "hybrid",
                                        expand_query=False,
                                        tenant_id=args.tenant_id,
                                        patient_id=args.patient_id,
                                        user_id=args.user_id,
                                        allow_unfiltered=args.allow_unfiltered_demo,
                                        trace=True,
                                    ))
                                    loop.close()
                                    retrieved_docs = [r.get("document_name") for r in response.results]
                                    trace_info = response.trace_info or {}
                                    dense_counts.append(trace_info.get("num_dense_results", 0))
                                    sparse_counts.append(trace_info.get("num_sparse_results", 0))
                                    merged_counts.append(trace_info.get("num_after_merge", 0))
                                    reranked_count += int(bool(response.reranked))
                        if not retrieved_docs and filters:
                            if method == "FAISS Only":
                                auth_probe_count = len(vector_backend.search(query, top_k=1, filters=None))
                            elif method == "BM25 Only":
                                auth_probe_count = len(bm25_backend.search(query, top_k=1, filters=None))
                            else:
                                auth_probe_count = max(
                                    len(vector_backend.search(query, top_k=1, filters=None)),
                                    len(bm25_backend.search(query, top_k=1, filters=None)),
                                )
                            if auth_probe_count > 0:
                                failure_counts["authorization_filter_rejection_count"] += 1
                    except Exception as exc:
                        retrieved_docs = []
                        failure_counts["exceptions"] += 1
                        if "BM25 sparse index is empty" in str(exc):
                            failure_counts["empty_index_failures"] += 1
                                
                    latency_ms = (time.perf_counter() - start_time) * 1000
                    latencies.append(latency_ms)
                    if not retrieved_docs:
                        failure_counts["no_results"] += 1
                    
                    # Convert to relevance label list (1 if relevant, 0 if not)
                    # A document is relevant if it belongs to this case's contexts
                    relevance_labels = []
                    for doc_name in retrieved_docs:
                        if doc_name in expected_doc_names:
                            relevance_labels.append(1)
                        else:
                            relevance_labels.append(0)
                            
                    # True total number of relevant documents for this query
                    total_relevant = max(1, len(expected_doc_names))
                    ideal_relevance = [1] * total_relevant + [0] * (5 - total_relevant)
                    
                    # MRR
                    first_rank = None
                    for rank, rel in enumerate(relevance_labels, start=1):
                        if rel == 1:
                            first_rank = rank
                            break
                    mrr = (1.0 / first_rank) if first_rank else 0.0
                    mrrs.append(mrr)
                    if not any(relevance_labels[:5]):
                        failure_counts["no_relevant_at_5"] += 1
                    
                    # Precision and Recall
                    for k in TOP_K_LIST:
                        k_relevance = relevance_labels[:k]
                        hits = sum(k_relevance)
                        precisions[k].append(hits / k)
                        recalls[k].append(hits / total_relevant)
                        ndcgs[k].append(calculate_ndcg(k_relevance, ideal_relevance, k))

                results_by_method[method] = {
                    "latency_mean": _mean(latencies),
                    "latency_p50": median(latencies),
                    "latency_p95": get_percentile(latencies, 0.95),
                    "latency_p99": get_percentile(latencies, 0.99),
                    "mrr": _mean(mrrs),
                    **{f"precision_at_{k}": _mean(precisions[k]) for k in TOP_K_LIST},
                    **{f"recall_at_{k}": _mean(recalls[k]) for k in TOP_K_LIST},
                    **{f"ndcg_at_{k}": _mean(ndcgs[k]) for k in TOP_K_LIST},
                    "zero_result_rate": failure_counts["no_results"] / len(cases) if cases else 0.0,
                    "failure_counts": failure_counts,
                    "candidate_counts": {
                        "dense_mean": _mean(dense_counts),
                        "sparse_mean": _mean(sparse_counts),
                        "merged_mean": _mean(merged_counts),
                        "reranked_query_count": reranked_count,
                    },
                }

            # Log system configuration
            print("\nSystem Configuration:")
            print(f"- Embedding Model: {settings.embedding_model}")
            print(f"- Embedding Dimension: {eff_dim}")
            print(f"- Configured Dimension: {settings.embedding_dim}")
            
            # Print Markdown Results Table
            print("\n## Retrieval Metrics Summary\n")
            print("| Method | Recall@1 | Recall@5 | Precision@5 | MRR | nDCG@5 | Latency (Mean/p50/p95 ms) |")
            print("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
            for method, metrics in results_by_method.items():
                print(
                    f"| {method} | {metrics['recall_at_1']:.4f} | {metrics['recall_at_5']:.4f} | "
                    f"{metrics['precision_at_5']:.4f} | {metrics['mrr']:.4f} | {metrics['ndcg_at_5']:.4f} | "
                    f"{metrics['latency_mean']:.2f} / {metrics['latency_p50']:.2f} / {metrics['latency_p95']:.2f} |"
                )
            
            # Save results to json
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output_json = args.output or (REPO_ROOT / "results" / f"retrieval_evaluation_results_{timestamp}.json")
            output_json.parent.mkdir(exist_ok=True)
            status_short = git_value(["status", "--short"]) or ""
            payload = {
                "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
                "artifact_type": "retrieval_quality_benchmark",
                "metadata": {
                    "timestamp": timestamp,
                    "seed": args.seed,
                    "benchmark_category": "retrieval-quality benchmark",
                    "evaluation_boundaries": {
                        "smoke_tests": "Fast endpoint and unit checks; not measured here.",
                        "deterministic_regression_tests": "Pytest retrieval regression coverage using real retrieval code and deterministic local embeddings.",
                        "retrieval_quality_benchmarks": "This script: synthetic answerable retrieval cases with dense, sparse, hybrid, and reranked hybrid modes.",
                        "live_model_evaluations": "Separate model/provider-backed generation checks; not run by this script.",
                    },
                    "code": {
                        "git_commit": git_value(["rev-parse", "HEAD"]),
                        "git_branch": git_value(["branch", "--show-current"]),
                        "working_tree_status_sha256_16": hashlib.sha256(status_short.encode("utf-8")).hexdigest()[:16],
                        "working_tree_dirty_entries": len([line for line in status_short.splitlines() if line.strip()]),
                    },
                    "note": (
                        "Synthetic retrieval regression benchmark. Retrieval metrics are computed only for answerable "
                        "cases with explicit required evidence targets. Do not describe these results as clinical "
                        "validation or SOTA clinical performance."
                    ),
                    "generated_at": timestamp,
                },
                "dataset": {
                    "path": str(args.dataset),
                    "sha256": sha256_file(args.dataset),
                    "line_count": len(cases) + skipped,
                    "query_count": len(cases),
                    "skipped_abstention_only_cases": skipped,
                },
                "code": {
                    "git_commit": git_value(["rev-parse", "HEAD"]),
                    "git_branch": git_value(["branch", "--show-current"]),
                    "working_tree_status_sha256_16": hashlib.sha256(status_short.encode("utf-8")).hexdigest()[:16],
                    "working_tree_dirty_entries": len([line for line in status_short.splitlines() if line.strip()]),
                },
                "runtime": {
                    "python": sys.version,
                    "platform": platform.platform(),
                    "executable": sys.executable,
                },
                "backend_mode": {
                    "mode": "temporary-faiss-and-in-memory-bm25",
                    "dense_backend": "faiss",
                    "sparse_backend": "memory-rank-bm25" if bm25_backend._index is not None else "memory-token-overlap",
                    "reranker": "optional-query-engine-reranker",
                    "allow_unfiltered": args.allow_unfiltered_demo,
                },
                "evaluated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "configuration": {
                    "embedding_model": settings.embedding_model,
                    "embedding_dimension": eff_dim,
                    "configured_embedding_dimension": settings.embedding_dim,
                    "chunk_size": settings.chunk_size,
                    "chunk_overlap": settings.chunk_overlap,
                    "use_hybrid_search": settings.use_hybrid_search,
                    "use_reranking": settings.use_reranking,
                    "use_query_expansion": settings.use_query_expansion,
                    "tenant_id": args.tenant_id,
                    "patient_id": args.patient_id,
                    "user_id": args.user_id,
                },
                "corpus_statistics": {
                    "context_document_count": sum(len(case["contexts"]) for case in cases),
                    "chunk_count": int(vector_stats.get("total_chunks") or 0),
                    "vector_stats": vector_stats,
                    "bm25_stats": bm25_stats,
                },
                "system_config": {
                    "embedding_model": settings.embedding_model,
                    "embedding_dimension": eff_dim,
                    "chunk_size": settings.chunk_size,
                    "chunk_overlap": settings.chunk_overlap,
                    "use_hybrid_search": settings.use_hybrid_search,
                    "use_reranking": settings.use_reranking,
                    "use_query_expansion": settings.use_query_expansion,
                    "bm25_stats": bm25_stats,
                },
                "results": results_by_method
            }
            validate_artifact_payload(payload)
            with open(output_json, "w", encoding="utf-8") as out_f:
                json.dump(payload, out_f, indent=2)
            print(f"\nSaved detailed retrieval metrics to {output_json}")

            if not args.no_markdown:
                markdown_output = args.markdown_output or output_json.with_suffix(".md")
                markdown_output.parent.mkdir(exist_ok=True)
                markdown_output.write_text(render_markdown_summary(payload), encoding="utf-8")
                print(f"Saved Markdown retrieval report to {markdown_output}")

if __name__ == "__main__":
    main()
