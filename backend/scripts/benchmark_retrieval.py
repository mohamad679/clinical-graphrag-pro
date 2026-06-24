#!/usr/bin/env python3
"""
Retrieval benchmark for Clinical GraphRAG Pro.

Benchmarks 4 retrieval modes against the golden evaluation dataset:
  A. FAISS only
  B. BM25 only
  C. Hybrid (FAISS + BM25 + RRF)
  D. Hybrid + cross-encoder reranker

Outputs:
  - docs/benchmark_results.json
  - Markdown summary printed to stdout
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Any
from unittest.mock import patch

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = BACKEND_DIR / "data" / "golden_evaluation_dataset.jsonl"
OUTPUT_PATH = REPO_ROOT / "docs" / "benchmark_results.json"
TOP_K = 5

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Align settings loading with the backend app's expected working directory,
# even if this script is launched from the repository root.
os.chdir(BACKEND_DIR)

from app.core.config import get_settings
from app.services.bm25_index import BM25Index
from app.services.query_engine import QueryEngine
from app.services import query_engine as query_engine_module
from app.services.reranker import reranker_service
from app.services.vector_store import FAISSBackend, SearchResult

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "had",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(slots=True)
class GoldenCase:
    question: str
    ground_truth: str
    contexts: list[str]


def load_cases(dataset_path: Path) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    with dataset_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            contexts = row.get("context") or row.get("contexts") or []
            if isinstance(contexts, str):
                contexts = [contexts]
            cases.append(
                GoldenCase(
                    question=str(row["question"]).strip(),
                    ground_truth=str(row["ground_truth"]).strip(),
                    contexts=[str(item).strip() for item in contexts if str(item).strip()],
                )
            )
    return cases


def extract_keywords(ground_truth: str) -> list[str]:
    tokens = re.findall(r"\b[\w-]+\b", ground_truth.lower())
    keywords: list[str] = []
    for token in tokens:
        if len(token) < 3 or token in STOPWORDS:
            continue
        if token not in keywords:
            keywords.append(token)
        if len(keywords) == 3:
            break
    if keywords:
        return keywords
    fallback = [token for token in tokens if len(token) >= 3]
    return fallback[:3] or tokens[:1]


def normalize_results(results: list[SearchResult] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in results:
        if isinstance(item, SearchResult):
            normalized.append(
                {
                    "chunk_text": item.chunk_text,
                    "chunk_index": item.chunk_index,
                    "document_id": item.document_id,
                    "document_name": item.document_name,
                    "score": float(item.score),
                    "chunk_id": item.chunk_id,
                    "page_start": item.page_start,
                    "page_end": item.page_end,
                    "source_offset_start": item.source_offset_start,
                    "source_offset_end": item.source_offset_end,
                }
            )
        else:
            normalized.append(
                {
                    "chunk_text": str(item.get("chunk_text", "")),
                    "chunk_index": int(item.get("chunk_index", 0)),
                    "document_id": str(item.get("document_id", "")),
                    "document_name": str(item.get("document_name", "")),
                    "score": float(item.get("score", 0.0)),
                    "chunk_id": str(item.get("chunk_id", "")),
                    "page_start": item.get("page_start"),
                    "page_end": item.get("page_end"),
                    "source_offset_start": item.get("source_offset_start"),
                    "source_offset_end": item.get("source_offset_end"),
                }
            )
    return normalized


def is_relevant(chunk_text: str, keywords: list[str]) -> bool:
    haystack = chunk_text.lower()
    return any(keyword in haystack for keyword in keywords)


def evaluate_query(results: list[dict[str, Any]], keywords: list[str]) -> tuple[float, float, int | None]:
    relevant_flags = [is_relevant(item["chunk_text"], keywords) for item in results[:TOP_K]]
    precision_at_5 = sum(1 for flag in relevant_flags if flag) / TOP_K
    first_relevant_rank = next((index + 1 for index, flag in enumerate(relevant_flags) if flag), None)
    mrr = (1.0 / first_relevant_rank) if first_relevant_rank else 0.0
    return precision_at_5, mrr, first_relevant_rank


def build_chunk_payloads(vector_backend: FAISSBackend, text: str, chunk_size: int, overlap: int) -> list[dict[str, Any]]:
    chunks = vector_backend.chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    payloads: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        payloads.append(
            {
                "chunk_id": chunk["chunk_id"],
                "chunk_index": index,
                "text": chunk["text"],
            }
        )
    return payloads


def build_rrf_candidates(
    vector_backend: FAISSBackend,
    bm25_backend: BM25Index,
    query: str,
    *,
    fetch_k: int,
) -> list[dict[str, Any]]:
    all_candidates: dict[str, dict[str, Any]] = {}

    vector_results = vector_backend.search(query, top_k=fetch_k)
    for rank, result in enumerate(vector_results):
        key = result.chunk_id or f"{result.document_id}:{result.chunk_index}"
        if key not in all_candidates:
            all_candidates[key] = {
                "chunk_text": result.chunk_text,
                "chunk_index": result.chunk_index,
                "document_id": result.document_id,
                "document_name": result.document_name,
                "chunk_id": result.chunk_id,
                "page_start": result.page_start,
                "page_end": result.page_end,
                "source_offset_start": result.source_offset_start,
                "source_offset_end": result.source_offset_end,
                "score": 0.0,
                "vector_score": 0.0,
                "bm25_score": 0.0,
                "vector_rank": None,
                "bm25_rank": None,
            }
        candidate = all_candidates[key]
        candidate["vector_score"] = max(candidate["vector_score"], float(result.score))
        current_rank = candidate["vector_rank"]
        candidate["vector_rank"] = rank if current_rank is None else min(current_rank, rank)

    bm25_results = bm25_backend.search(query, top_k=fetch_k)
    for rank, result in enumerate(bm25_results):
        key = result.get("chunk_id") or f"{result['document_id']}:{result['chunk_index']}"
        if key not in all_candidates:
            all_candidates[key] = {
                "chunk_text": result["chunk_text"],
                "chunk_index": int(result["chunk_index"]),
                "document_id": str(result["document_id"]),
                "document_name": str(result["document_name"]),
                "chunk_id": str(result.get("chunk_id", "")),
                "page_start": result.get("page_start"),
                "page_end": result.get("page_end"),
                "source_offset_start": result.get("source_offset_start"),
                "source_offset_end": result.get("source_offset_end"),
                "score": 0.0,
                "vector_score": 0.0,
                "bm25_score": 0.0,
                "vector_rank": None,
                "bm25_rank": None,
            }
        candidate = all_candidates[key]
        candidate["bm25_score"] = max(candidate["bm25_score"], float(result.get("score", 0.0)))
        current_rank = candidate["bm25_rank"]
        candidate["bm25_rank"] = rank if current_rank is None else min(current_rank, rank)

    return list(all_candidates.values())


def summarize_latencies(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
        "avg_ms": round(fmean(values), 3),
    }


async def benchmark_mode_faiss(
    cases: list[GoldenCase],
    *,
    settings: Any,
    vector_backend: FAISSBackend,
) -> dict[str, Any]:
    latency_ms: list[float] = []
    precision_values: list[float] = []
    mrr_values: list[float] = []
    per_query: list[dict[str, Any]] = []

    with (
        patch.object(settings, "use_hybrid_search", False),
        patch.object(settings, "use_reranking", False),
        patch.object(settings, "use_query_expansion", False),
    ):
        for case in cases:
            keywords = extract_keywords(case.ground_truth)
            started = perf_counter()
            results = normalize_results(vector_backend.search(case.question, top_k=TOP_K))
            elapsed_ms = (perf_counter() - started) * 1000
            precision_at_5, mrr, first_rank = evaluate_query(results, keywords)
            latency_ms.append(elapsed_ms)
            precision_values.append(precision_at_5)
            mrr_values.append(mrr)
            per_query.append(
                {
                    "question": case.question,
                    "keywords": keywords,
                    "latency_ms": round(elapsed_ms, 3),
                    "precision_at_5": round(precision_at_5, 4),
                    "mrr": round(mrr, 4),
                    "first_relevant_rank": first_rank,
                    "results": results,
                }
            )

    return {
        "label": "FAISS only",
        "avg_latency_ms": round(fmean(latency_ms), 3),
        "precision_at_5": round(fmean(precision_values), 4),
        "mrr": round(fmean(mrr_values), 4),
        "per_query": per_query,
    }


async def benchmark_mode_bm25(
    cases: list[GoldenCase],
    *,
    settings: Any,
    bm25_backend: BM25Index,
) -> dict[str, Any]:
    latency_ms: list[float] = []
    precision_values: list[float] = []
    mrr_values: list[float] = []
    per_query: list[dict[str, Any]] = []

    with (
        patch.object(settings, "use_hybrid_search", False),
        patch.object(settings, "use_reranking", False),
        patch.object(settings, "use_query_expansion", False),
    ):
        for case in cases:
            keywords = extract_keywords(case.ground_truth)
            started = perf_counter()
            results = normalize_results(bm25_backend.search(case.question, top_k=TOP_K))
            elapsed_ms = (perf_counter() - started) * 1000
            precision_at_5, mrr, first_rank = evaluate_query(results, keywords)
            latency_ms.append(elapsed_ms)
            precision_values.append(precision_at_5)
            mrr_values.append(mrr)
            per_query.append(
                {
                    "question": case.question,
                    "keywords": keywords,
                    "latency_ms": round(elapsed_ms, 3),
                    "precision_at_5": round(precision_at_5, 4),
                    "mrr": round(mrr, 4),
                    "first_relevant_rank": first_rank,
                    "results": results,
                }
            )

    return {
        "label": "BM25 only",
        "avg_latency_ms": round(fmean(latency_ms), 3),
        "precision_at_5": round(fmean(precision_values), 4),
        "mrr": round(fmean(mrr_values), 4),
        "per_query": per_query,
    }


async def benchmark_mode_query_engine(
    cases: list[GoldenCase],
    *,
    settings: Any,
    vector_backend: FAISSBackend,
    bm25_backend: BM25Index,
    use_reranking: bool,
) -> dict[str, Any]:
    engine = QueryEngine()
    latency_ms: list[float] = []
    precision_values: list[float] = []
    mrr_values: list[float] = []
    per_query: list[dict[str, Any]] = []

    label = "Hybrid + cross-encoder reranker" if use_reranking else "Hybrid FAISS+BM25 + RRF"

    with (
        patch.object(query_engine_module, "vector_store_service", vector_backend),
        patch.object(query_engine_module, "bm25_index", bm25_backend),
        patch.object(settings, "use_hybrid_search", True),
        patch.object(settings, "use_reranking", use_reranking),
        patch.object(settings, "use_query_expansion", False),
    ):
        for case in cases:
            keywords = extract_keywords(case.ground_truth)
            started = perf_counter()
            response = await engine.query(case.question, top_k=TOP_K)
            elapsed_ms = (perf_counter() - started) * 1000
            results = normalize_results(response.results)
            precision_at_5, mrr, first_rank = evaluate_query(results, keywords)
            latency_ms.append(elapsed_ms)
            precision_values.append(precision_at_5)
            mrr_values.append(mrr)
            per_query.append(
                {
                    "question": case.question,
                    "keywords": keywords,
                    "latency_ms": round(elapsed_ms, 3),
                    "precision_at_5": round(precision_at_5, 4),
                    "mrr": round(mrr, 4),
                    "first_relevant_rank": first_rank,
                    "retrieval_method": response.retrieval_method,
                    "reranked": response.reranked,
                    "total_candidates": response.total_candidates,
                    "results": results,
                }
            )

    return {
        "label": label,
        "avg_latency_ms": round(fmean(latency_ms), 3),
        "precision_at_5": round(fmean(precision_values), 4),
        "mrr": round(fmean(mrr_values), 4),
        "per_query": per_query,
    }


async def measure_operation_latencies(
    cases: list[GoldenCase],
    *,
    vector_backend: FAISSBackend,
    bm25_backend: BM25Index,
    reranker_available: bool,
) -> dict[str, Any]:
    embedder = vector_backend._get_embedder()
    index = vector_backend._get_index()
    engine = QueryEngine()
    fetch_k = TOP_K * 3

    embedding_generation_ms: list[float] = []
    faiss_search_ms: list[float] = []
    bm25_search_ms: list[float] = []
    rrf_fusion_ms: list[float] = []
    cross_encoder_rerank_ms: list[float] = []

    for case in cases:
        started = perf_counter()
        query_embedding = embedder.encode([case.question], normalize_embeddings=True, show_progress_bar=False)
        embedding_generation_ms.append((perf_counter() - started) * 1000)

        started = perf_counter()
        index.search(np.array(query_embedding, dtype=np.float32), min(max(TOP_K, 1) * 4, index.ntotal))
        faiss_search_ms.append((perf_counter() - started) * 1000)

        started = perf_counter()
        bm25_backend.search(case.question, top_k=TOP_K)
        bm25_search_ms.append((perf_counter() - started) * 1000)

        candidates = build_rrf_candidates(vector_backend, bm25_backend, case.question, fetch_k=fetch_k)

        started = perf_counter()
        fused_candidates = engine._rrf_merge([dict(candidate) for candidate in candidates])
        rrf_fusion_ms.append((perf_counter() - started) * 1000)

        if reranker_available:
            started = perf_counter()
            reranker_service.rerank(case.question, fused_candidates[:fetch_k], top_k=TOP_K)
            cross_encoder_rerank_ms.append((perf_counter() - started) * 1000)

    return {
        "embedding_generation": summarize_latencies(embedding_generation_ms),
        "faiss_vector_search": summarize_latencies(faiss_search_ms),
        "bm25_search": summarize_latencies(bm25_search_ms),
        "rrf_fusion": summarize_latencies(rrf_fusion_ms),
        "cross_encoder_rerank_top_5": summarize_latencies(cross_encoder_rerank_ms),
    }


def print_markdown_table(mode_rows: list[tuple[str, dict[str, Any]]], embedding_load_ms: float) -> None:
    print("# Retrieval Benchmark")
    print("")
    print(f"Embedding model load: {embedding_load_ms:.3f} ms")
    print("")
    print("| Mode | Avg Latency (ms) | Precision@5 | MRR |")
    print("| --- | ---: | ---: | ---: |")
    for _, row in mode_rows:
        print(
            f"| {row['label']} | {row['avg_latency_ms']:.3f} | "
            f"{row['precision_at_5']:.4f} | {row['mrr']:.4f} |"
        )
    print("")
    print("Regenerate: cd backend && python scripts/benchmark_retrieval.py")


async def main() -> None:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Golden dataset not found at {DATASET_PATH}")

    cases = load_cases(DATASET_PATH)
    if not cases:
        raise RuntimeError("Golden dataset is empty.")

    settings = get_settings()
    original_chunk_size = settings.chunk_size
    original_chunk_overlap = settings.chunk_overlap
    original_embedding_model = settings.embedding_model
    original_reranker_model = settings.reranker_model

    with tempfile.TemporaryDirectory(prefix="clinical-graphrag-benchmark-") as temp_dir:
        temp_vector_dir = Path(temp_dir) / "vector_store"
        temp_vector_dir.mkdir(parents=True, exist_ok=True)

        with (
            patch.object(settings, "vector_backend", "faiss"),
            patch.object(settings, "vector_store_dir", temp_vector_dir),
        ):
            vector_backend = FAISSBackend()
            bm25_backend = BM25Index(use_database=False)

            embedder_started = perf_counter()
            embedder = vector_backend._get_embedder()
            embedding_model_load_ms = (perf_counter() - embedder_started) * 1000
            effective_embedding_dim = int(embedder.get_sentence_embedding_dimension())

            reranker_model_load_ms: float | None = None
            reranker_available = False
            try:
                reranker_started = perf_counter()
                reranker_service._get_model()
                reranker_model_load_ms = (perf_counter() - reranker_started) * 1000
                reranker_available = True
            except Exception:
                reranker_available = False

            with patch.object(settings, "embedding_dim", effective_embedding_dim):
                total_chunks = 0
                for index, case in enumerate(cases, start=1):
                    for context_index, context_text in enumerate(case.contexts, start=1):
                        document_id = f"benchmark-case-{index:02d}-ctx-{context_index:02d}"
                        document_name = f"golden_case_{index:02d}_context_{context_index:02d}.txt"
                        chunk_payloads = build_chunk_payloads(
                            vector_backend,
                            context_text,
                            chunk_size=settings.chunk_size,
                            overlap=settings.chunk_overlap,
                        )
                        vector_backend.add_documents(
                            document_id=document_id,
                            document_name=document_name,
                            text=context_text,
                            chunk_size=settings.chunk_size,
                            overlap=settings.chunk_overlap,
                            metadata={"benchmark_case": index, "source": "golden_evaluation_dataset"},
                            chunks=chunk_payloads,
                        )
                        bm25_backend.add_document(chunk_payloads, document_id, document_name)
                        total_chunks += len(chunk_payloads)

                mode_rows = [
                    ("mode_a", await benchmark_mode_faiss(cases, settings=settings, vector_backend=vector_backend)),
                    ("mode_b", await benchmark_mode_bm25(cases, settings=settings, bm25_backend=bm25_backend)),
                    (
                        "mode_c",
                        await benchmark_mode_query_engine(
                            cases,
                            settings=settings,
                            vector_backend=vector_backend,
                            bm25_backend=bm25_backend,
                            use_reranking=False,
                        ),
                    ),
                    (
                        "mode_d",
                        await benchmark_mode_query_engine(
                            cases,
                            settings=settings,
                            vector_backend=vector_backend,
                            bm25_backend=bm25_backend,
                            use_reranking=True,
                        ),
                    ),
                ]

                operation_latencies = await measure_operation_latencies(
                    cases,
                    vector_backend=vector_backend,
                    bm25_backend=bm25_backend,
                    reranker_available=reranker_available,
                )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "path": str(DATASET_PATH.relative_to(REPO_ROOT)),
            "cases": len(cases),
            "corpus_documents": sum(len(case.contexts) for case in cases),
            "corpus_chunks": total_chunks,
        },
        "configuration": {
            "embedding_model": original_embedding_model,
            "configured_embedding_dim": settings.embedding_dim,
            "effective_embedding_dim": effective_embedding_dim,
            "reranker_model": original_reranker_model,
            "chunk_size": original_chunk_size,
            "chunk_overlap": original_chunk_overlap,
            "top_k": TOP_K,
        },
        "model_loading_ms": {
            "embedding_model": round(embedding_model_load_ms, 3),
            "reranker_model": round(reranker_model_load_ms, 3) if reranker_model_load_ms is not None else None,
        },
        "reranker_available": reranker_available,
        "operation_latency_ms": operation_latencies,
        "modes": {mode_key: row for mode_key, row in mode_rows},
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print_markdown_table(mode_rows, embedding_model_load_ms)


if __name__ == "__main__":
    asyncio.run(main())
