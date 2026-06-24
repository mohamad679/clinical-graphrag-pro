#!/usr/bin/env python3
"""
Lightweight benchmark runner for Clinical GraphRAG Pro.

Runs:
  - MedQA-style multiple choice evaluation against the configured LLM
  - Retrieval quality benchmarking against the currently indexed chunk corpus

The script is designed to be honest about environment constraints:
if the LLM is unreachable or unauthenticated, MedQA is marked as failed rather
than replaced with synthetic results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import pickle
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Any
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DATA_DIR = BACKEND_DIR / "app" / "data" / "benchmarks"
MEDQA_PATH = BENCHMARK_DATA_DIR / "medqa_100.jsonl"
RETRIEVAL_PATH = BENCHMARK_DATA_DIR / "retrieval_pairs.jsonl"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "results" / "benchmark_2026.json"
DEFAULT_MARKDOWN_PATH = REPO_ROOT / "results" / "BENCHMARK.md"
BENCHMARK_SYSTEM_PROMPT = (
    "You are a board-style clinical reasoning evaluator. "
    "Choose the single best answer. Be deterministic and concise."
)
LETTER_PATTERN = re.compile(r"^\s*([A-D])\b", re.IGNORECASE)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load backend/.env rather than the repository-root .env. The root file in this
# repo is not guaranteed to be parseable by the settings model.
os.chdir(BACKEND_DIR)

from app.core.config import get_settings
from app.services.bm25_index import BM25Index
from app.services.llm import llm_service
from app.services.query_engine import QueryEngine
from app.services import query_engine as query_engine_module
from app.services.vector_store import FAISSBackend


@dataclass(slots=True)
class CorpusRuntime:
    vector_backend: FAISSBackend | None
    bm25_backend: BM25Index
    chunk_count: int
    document_count: int
    source_paths: list[str]
    embedding_model: str
    embedding_load_ms: float | None = None
    effective_embedding_dim: int | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Clinical GraphRAG Pro benchmark.")
    parser.add_argument(
        "--mode",
        choices=["medqa", "rag_quality", "all"],
        default="all",
        help="Which benchmark sections to run.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=100,
        help="Maximum number of MedQA questions to evaluate.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to the JSON results file.",
    )
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def safe_float(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def seconds_from_ms(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value / 1000:.2f}s"


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    values = sorted(values)
    index = (len(values) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(values[lower])
    weight = index - lower
    return float(values[lower] * (1 - weight) + values[upper] * weight)


def render_progress(current: int, total: int, prefix: str) -> None:
    total = max(total, 1)
    width = 28
    filled = int(width * current / total)
    bar = "#" * filled + "-" * (width - filled)
    print(f"\r{prefix} [{bar}] {current}/{total}", end="", flush=True)
    if current >= total:
        print("")


def extract_answer_letter(text: str) -> str | None:
    if not text:
        return None
    first_line = text.splitlines()[0] if text.splitlines() else text
    match = LETTER_PATTERN.search(first_line)
    if match:
        return match.group(1).upper()
    match = re.search(r"\b([A-D])\b", text.strip(), flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def format_options(options: dict[str, str]) -> str:
    return "  ".join(f"{letter}. {text}" for letter, text in sorted(options.items()))


def build_direct_prompt(question_row: dict[str, Any]) -> str:
    return (
        "You are a medical expert. Answer this question.\n"
        f"Question: {question_row['question']}\n"
        f"Options: {format_options(question_row['options'])}\n\n"
        "Respond with ONLY the letter (A, B, C, or D) on the first line.\n"
        "Then explain your reasoning in 2-3 sentences."
    )


def build_rag_prompt(question_row: dict[str, Any], context: str) -> str:
    return (
        "Relevant medical context:\n"
        f"{context}\n\n"
        "Based on this context and your medical knowledge, answer:\n"
        f"Question: {question_row['question']}\n"
        f"Options: {format_options(question_row['options'])}\n\n"
        "Respond with ONLY the letter (A, B, C, or D) on the first line.\n"
        "Then explain your reasoning in 2-3 sentences."
    )


def load_existing_results(output_path: Path) -> dict[str, Any] | None:
    if not output_path.exists():
        return None
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_medqa_resume_map(existing: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not existing:
        return {}
    medqa = existing.get("medqa") or {}
    per_question = medqa.get("per_question") or []
    return {str(row.get("question_id")): row for row in per_question if row.get("question_id")}


def load_persisted_chunks() -> tuple[list[dict[str, Any]], list[str]]:
    settings = get_settings()
    candidate_dirs = [
        settings.vector_store_dir,
        BACKEND_DIR / "data" / "vector_store",
        REPO_ROOT / "data" / "vector_store",
    ]
    chunks: list[dict[str, Any]] = []
    source_paths: list[str] = []
    seen: set[tuple[str, str, int]] = set()

    for directory in candidate_dirs:
        chunk_path = directory / "chunks.pkl"
        if not chunk_path.exists():
            continue
        try:
            raw = pickle.load(chunk_path.open("rb"))
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        resolved_chunk_path = chunk_path.resolve()
        try:
            display_path = str(resolved_chunk_path.relative_to(REPO_ROOT))
        except ValueError:
            display_path = str(resolved_chunk_path)
        source_paths.append(display_path)
        for item in raw:
            if not isinstance(item, dict):
                continue
            document_id = str(item.get("document_id") or "")
            chunk_id = str(item.get("chunk_id") or "")
            chunk_index = int(item.get("chunk_index") or 0)
            key = (document_id, chunk_id or f"idx:{chunk_index}", chunk_index)
            if key in seen:
                continue
            seen.add(key)
            chunk_text = str(item.get("chunk_text") or item.get("text") or "").strip()
            if not chunk_text:
                continue
            chunks.append(
                {
                    "chunk_id": chunk_id or f"{document_id}:{chunk_index}",
                    "chunk_index": chunk_index,
                    "chunk_text": chunk_text,
                    "document_id": document_id,
                    "document_name": str(item.get("document_name") or "unknown"),
                    "page_start": item.get("page_start"),
                    "page_end": item.get("page_end"),
                    "source_offset_start": item.get("source_offset_start"),
                    "source_offset_end": item.get("source_offset_end"),
                    "metadata": dict(item.get("metadata") or {}),
                }
            )

    return chunks, source_paths


def build_corpus_runtime() -> tuple[CorpusRuntime, tempfile.TemporaryDirectory[str] | None]:
    settings = get_settings()
    chunks, source_paths = load_persisted_chunks()
    bm25_backend = BM25Index(use_database=False)

    if not chunks:
        runtime = CorpusRuntime(
            vector_backend=None,
            bm25_backend=bm25_backend,
            chunk_count=0,
            document_count=0,
            source_paths=source_paths,
            embedding_model=settings.embedding_model,
        )
        return runtime, None

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        groups[(chunk["document_id"], chunk["document_name"])].append(chunk)

    temp_dir = tempfile.TemporaryDirectory(prefix="clinical-graphrag-benchmark-runtime-")
    temp_vector_dir = Path(temp_dir.name) / "vector_store"
    temp_vector_dir.mkdir(parents=True, exist_ok=True)

    with (
        patch.object(settings, "vector_backend", "faiss"),
        patch.object(settings, "vector_store_dir", temp_vector_dir),
    ):
        vector_backend = FAISSBackend()
        embedder_started = perf_counter()
        embedder = vector_backend._get_embedder()
        embedding_load_ms = (perf_counter() - embedder_started) * 1000
        effective_dim = int(embedder.get_sentence_embedding_dimension())

        with patch.object(settings, "embedding_dim", effective_dim):
            for (document_id, document_name), document_chunks in groups.items():
                payload = [
                    {
                        "chunk_id": chunk["chunk_id"],
                        "chunk_index": chunk["chunk_index"],
                        "text": chunk["chunk_text"],
                        "page_start": chunk.get("page_start"),
                        "page_end": chunk.get("page_end"),
                        "source_offset_start": chunk.get("source_offset_start"),
                        "source_offset_end": chunk.get("source_offset_end"),
                        "metadata": dict(chunk.get("metadata") or {}),
                    }
                    for chunk in sorted(document_chunks, key=lambda item: item["chunk_index"])
                ]
                vector_backend.add_documents(
                    document_id=document_id,
                    document_name=document_name,
                    text="",
                    chunk_size=settings.chunk_size,
                    overlap=settings.chunk_overlap,
                    chunks=payload,
                )
                bm25_backend.add_document(payload, document_id=document_id, document_name=document_name)

    runtime = CorpusRuntime(
        vector_backend=vector_backend,
        bm25_backend=bm25_backend,
        chunk_count=len(chunks),
        document_count=len(groups),
        source_paths=source_paths,
        embedding_model=settings.embedding_model,
        embedding_load_ms=round(embedding_load_ms, 3),
        effective_embedding_dim=effective_dim,
    )
    return runtime, temp_dir


def build_context_from_results(results: list[Any], limit: int = 3) -> str:
    if not results:
        return "No retrieved context was available."
    lines: list[str] = []
    for idx, result in enumerate(results[:limit], start=1):
        if isinstance(result, dict):
            document_name = str(result.get("document_name") or "unknown")
            text = str(result.get("chunk_text") or "")
        else:
            document_name = str(getattr(result, "document_name", "unknown"))
            text = str(getattr(result, "chunk_text", ""))
        lines.append(f"[CTX{idx}] {document_name}: {text}")
    return "\n".join(lines)


async def evaluate_llm_answer(prompt: str) -> tuple[str | None, str, float, str, str]:
    started = perf_counter()
    response = await llm_service.generate_with_metadata(
        prompt,
        system_prompt=BENCHMARK_SYSTEM_PROMPT,
        temperature=0.0,
        max_tokens=256,
    )
    latency_ms = (perf_counter() - started) * 1000
    return (
        extract_answer_letter(response.text),
        response.text,
        latency_ms,
        response.provider,
        response.model_used,
    )


def ensure_output_shell(output_path: Path) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "metadata": {
            "generated_at": timestamp,
            "generated_date": timestamp[:10],
            "script": "backend/scripts/run_benchmark.py",
            "medqa_dataset": str(MEDQA_PATH.relative_to(REPO_ROOT)),
            "retrieval_dataset": str(RETRIEVAL_PATH.relative_to(REPO_ROOT)),
        },
        "medqa": {
            "status": "not_run",
            "questions_requested": 0,
            "questions_evaluated": 0,
            "model": None,
            "provider": None,
            "accuracy_direct": None,
            "accuracy_rag": None,
            "latency_direct_ms_mean": None,
            "latency_rag_ms_mean": None,
            "latency_p95_ms": None,
            "per_question": [],
            "by_category": {},
            "error": None,
        },
        "rag_quality": {
            "status": "not_run",
            "pair_count": 0,
            "faiss_keyword_hit_rate": None,
            "bm25_keyword_hit_rate": None,
            "hybrid_keyword_hit_rate": None,
            "faiss_top5_hit_rate": None,
            "bm25_top5_hit_rate": None,
            "hybrid_top5_hit_rate": None,
            "latency_ms_mean": {},
            "per_query": [],
            "error": None,
        },
        "corpus": {},
        "errors": [],
    }


def summarize_medqa(per_question: list[dict[str, Any]]) -> dict[str, Any]:
    if not per_question:
        return {
            "accuracy_direct": None,
            "accuracy_rag": None,
            "latency_direct_ms_mean": None,
            "latency_rag_ms_mean": None,
            "latency_p95_ms": None,
            "by_category": {},
        }

    direct_values = [1.0 if row["direct_correct"] else 0.0 for row in per_question]
    rag_values = [1.0 if row["rag_correct"] else 0.0 for row in per_question]
    direct_latencies = [float(row["latency_direct_ms"]) for row in per_question]
    rag_latencies = [float(row["latency_rag_ms"]) for row in per_question]

    by_category: dict[str, dict[str, Any]] = {}
    category_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_question:
        category_groups[row["category"]].append(row)

    for category, rows in sorted(category_groups.items()):
        cat_direct = fmean(1.0 if row["direct_correct"] else 0.0 for row in rows)
        cat_rag = fmean(1.0 if row["rag_correct"] else 0.0 for row in rows)
        by_category[category] = {
            "count": len(rows),
            "accuracy_direct": round(cat_direct, 4),
            "accuracy_rag": round(cat_rag, 4),
            "delta": round(cat_rag - cat_direct, 4),
        }

    combined_latencies = direct_latencies + rag_latencies
    return {
        "accuracy_direct": round(fmean(direct_values), 4),
        "accuracy_rag": round(fmean(rag_values), 4),
        "latency_direct_ms_mean": round(fmean(direct_latencies), 3),
        "latency_rag_ms_mean": round(fmean(rag_latencies), 3),
        "latency_p95_ms": round(percentile(combined_latencies, 0.95) or 0.0, 3),
        "by_category": by_category,
    }


async def run_medqa(
    *,
    n: int,
    runtime: CorpusRuntime,
    results: dict[str, Any],
    output_path: Path,
) -> None:
    rows = load_jsonl(MEDQA_PATH)[: max(n, 0)]
    resume_map = get_medqa_resume_map(results)
    completed: list[dict[str, Any]] = [resume_map[row["id"]] for row in rows if row["id"] in resume_map]
    pending = [row for row in rows if row["id"] not in resume_map]

    results["medqa"]["status"] = "running"
    results["medqa"]["questions_requested"] = len(rows)
    results["medqa"]["questions_evaluated"] = len(completed)
    save_json(output_path, results)

    processed = len(completed)
    total = len(rows)
    if processed:
        render_progress(processed, total, "MedQA")

    error_message: str | None = None
    for row in pending:
        question_id = str(row["id"])
        direct_prompt = build_direct_prompt(row)

        try:
            direct_answer, direct_response, direct_latency_ms, provider, model_name = await evaluate_llm_answer(
                direct_prompt
            )

            retrieved = (
                runtime.vector_backend.search(row["question"], top_k=3)
                if runtime.vector_backend is not None and runtime.chunk_count
                else []
            )
            rag_prompt = build_rag_prompt(row, build_context_from_results(retrieved, limit=3))
            rag_answer, rag_response, rag_latency_ms, _, _ = await evaluate_llm_answer(rag_prompt)

            record = {
                "question_id": question_id,
                "category": row["category"],
                "difficulty": row["difficulty"],
                "question": row["question"],
                "correct_answer": row["answer"],
                "direct_answer": direct_answer,
                "direct_correct": direct_answer == row["answer"],
                "rag_answer": rag_answer,
                "rag_correct": rag_answer == row["answer"],
                "latency_direct_ms": round(direct_latency_ms, 3),
                "latency_rag_ms": round(rag_latency_ms, 3),
                "retrieved_context_count": len(retrieved),
                "retrieved_documents": [
                    {
                        "document_name": result.document_name,
                        "score": round(float(result.score), 6),
                    }
                    for result in retrieved
                ],
                "direct_response_preview": direct_response[:400],
                "rag_response_preview": rag_response[:400],
            }
            completed.append(record)
            results["medqa"]["provider"] = provider
            results["medqa"]["model"] = model_name
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            results["errors"].append(
                {
                    "section": "medqa",
                    "question_id": question_id,
                    "error": error_message,
                }
            )
            break

        processed += 1
        results["medqa"]["questions_evaluated"] = processed
        results["medqa"]["per_question"] = completed
        if processed % 10 == 0 or processed == total:
            summary = summarize_medqa(completed)
            results["medqa"].update(summary)
            save_json(output_path, results)
        render_progress(processed, total, "MedQA")

    if error_message:
        summary = summarize_medqa(completed)
        results["medqa"].update(summary)
        results["medqa"]["status"] = "failed"
        results["medqa"]["error"] = error_message
        results["medqa"]["per_question"] = completed
        results["medqa"]["questions_evaluated"] = len(completed)
    else:
        summary = summarize_medqa(completed)
        results["medqa"].update(summary)
        results["medqa"]["status"] = "completed"
        results["medqa"]["error"] = None
        results["medqa"]["per_question"] = completed

    save_json(output_path, results)


def keyword_hit_rate(results: list[dict[str, Any]], expected_keywords: list[str]) -> tuple[float, bool, list[str]]:
    haystack = " ".join(str(item.get("chunk_text", "")) for item in results).lower()
    found = [keyword for keyword in expected_keywords if keyword.lower() in haystack]
    total = max(len(expected_keywords), 1)
    return len(found) / total, bool(found), found


async def run_retrieval_quality(
    *,
    runtime: CorpusRuntime,
    results: dict[str, Any],
    output_path: Path,
) -> None:
    rows = load_jsonl(RETRIEVAL_PATH)
    settings = get_settings()
    engine = QueryEngine()

    per_query: list[dict[str, Any]] = []
    latency_buckets: dict[str, list[float]] = {
        "faiss_ms": [],
        "bm25_ms": [],
        "hybrid_ms": [],
    }
    hit_buckets: dict[str, list[float]] = {
        "faiss": [],
        "bm25": [],
        "hybrid": [],
    }
    top5_buckets: dict[str, list[float]] = {
        "faiss": [],
        "bm25": [],
        "hybrid": [],
    }

    results["rag_quality"]["status"] = "running"
    results["rag_quality"]["pair_count"] = len(rows)
    save_json(output_path, results)

    render_progress(0, len(rows), "Retrieval")

    with (
        patch.object(query_engine_module, "vector_store_service", runtime.vector_backend),
        patch.object(query_engine_module, "bm25_index", runtime.bm25_backend),
        patch.object(settings, "use_hybrid_search", True),
        patch.object(settings, "use_reranking", False),
        patch.object(settings, "use_query_expansion", False),
    ):
        for index, row in enumerate(rows, start=1):
            query = str(row["query"])
            expected_keywords = [str(keyword) for keyword in row["expected_keywords"]]

            started = perf_counter()
            faiss_results = (
                runtime.vector_backend.search(query, top_k=5)
                if runtime.vector_backend is not None and runtime.chunk_count
                else []
            )
            faiss_ms = (perf_counter() - started) * 1000

            started = perf_counter()
            bm25_results = runtime.bm25_backend.search(query, top_k=5)
            bm25_ms = (perf_counter() - started) * 1000

            if runtime.vector_backend is not None:
                started = perf_counter()
                hybrid_response = await engine.query(
                    query,
                    top_k=5,
                    use_hybrid=True,
                    use_reranking=False,
                    expand_query=False,
                )
                hybrid_ms = (perf_counter() - started) * 1000
                hybrid_results_payload = hybrid_response.results
                hybrid_method = hybrid_response.retrieval_method
            else:
                hybrid_ms = 0.0
                hybrid_results_payload = []
                hybrid_method = "hybrid"

            faiss_serialized = [
                {
                    "document_name": item.document_name,
                    "document_id": item.document_id,
                    "chunk_text": item.chunk_text,
                    "score": round(float(item.score), 6),
                }
                for item in faiss_results
            ]
            bm25_serialized = [
                {
                    "document_name": item.get("document_name"),
                    "document_id": item.get("document_id"),
                    "chunk_text": item.get("chunk_text", ""),
                    "score": round(float(item.get("score", 0.0)), 6),
                }
                for item in bm25_results
            ]
            hybrid_serialized = [
                {
                    "document_name": item.get("document_name"),
                    "document_id": item.get("document_id"),
                    "chunk_text": item.get("chunk_text", ""),
                    "score": round(float(item.get("score", 0.0)), 6),
                }
                for item in hybrid_results_payload
            ]

            faiss_hit_rate, faiss_top5, faiss_found = keyword_hit_rate(faiss_serialized, expected_keywords)
            bm25_hit_rate, bm25_top5, bm25_found = keyword_hit_rate(bm25_serialized, expected_keywords)
            hybrid_hit_rate, hybrid_top5, hybrid_found = keyword_hit_rate(hybrid_serialized, expected_keywords)

            latency_buckets["faiss_ms"].append(faiss_ms)
            latency_buckets["bm25_ms"].append(bm25_ms)
            latency_buckets["hybrid_ms"].append(hybrid_ms)
            hit_buckets["faiss"].append(faiss_hit_rate)
            hit_buckets["bm25"].append(bm25_hit_rate)
            hit_buckets["hybrid"].append(hybrid_hit_rate)
            top5_buckets["faiss"].append(1.0 if faiss_top5 else 0.0)
            top5_buckets["bm25"].append(1.0 if bm25_top5 else 0.0)
            top5_buckets["hybrid"].append(1.0 if hybrid_top5 else 0.0)

            per_query.append(
                {
                    "query": query,
                    "expected_topic": row["expected_topic"],
                    "expected_keywords": expected_keywords,
                    "faiss": {
                        "keyword_hit_rate": round(faiss_hit_rate, 4),
                        "top5_hit": faiss_top5,
                        "keywords_found": faiss_found,
                        "latency_ms": round(faiss_ms, 3),
                        "results": faiss_serialized,
                    },
                    "bm25": {
                        "keyword_hit_rate": round(bm25_hit_rate, 4),
                        "top5_hit": bm25_top5,
                        "keywords_found": bm25_found,
                        "latency_ms": round(bm25_ms, 3),
                        "results": bm25_serialized,
                    },
                    "hybrid": {
                        "keyword_hit_rate": round(hybrid_hit_rate, 4),
                        "top5_hit": hybrid_top5,
                        "keywords_found": hybrid_found,
                        "latency_ms": round(hybrid_ms, 3),
                        "retrieval_method": hybrid_method,
                        "results": hybrid_serialized,
                    },
                }
            )

            if index % 10 == 0 or index == len(rows):
                results["rag_quality"]["per_query"] = per_query
                save_json(output_path, results)
            render_progress(index, len(rows), "Retrieval")

    results["rag_quality"].update(
        {
            "status": "completed",
            "faiss_keyword_hit_rate": round(fmean(hit_buckets["faiss"]), 4) if hit_buckets["faiss"] else None,
            "bm25_keyword_hit_rate": round(fmean(hit_buckets["bm25"]), 4) if hit_buckets["bm25"] else None,
            "hybrid_keyword_hit_rate": round(fmean(hit_buckets["hybrid"]), 4) if hit_buckets["hybrid"] else None,
            "faiss_top5_hit_rate": round(fmean(top5_buckets["faiss"]), 4) if top5_buckets["faiss"] else None,
            "bm25_top5_hit_rate": round(fmean(top5_buckets["bm25"]), 4) if top5_buckets["bm25"] else None,
            "hybrid_top5_hit_rate": round(fmean(top5_buckets["hybrid"]), 4) if top5_buckets["hybrid"] else None,
            "latency_ms_mean": {
                "faiss": round(fmean(latency_buckets["faiss_ms"]), 3) if latency_buckets["faiss_ms"] else None,
                "bm25": round(fmean(latency_buckets["bm25_ms"]), 3) if latency_buckets["bm25_ms"] else None,
                "hybrid": round(fmean(latency_buckets["hybrid_ms"]), 3) if latency_buckets["hybrid_ms"] else None,
            },
            "per_query": per_query,
            "error": None,
        }
    )
    save_json(output_path, results)


def benchmark_markdown(results: dict[str, Any]) -> str:
    metadata = results.get("metadata") or {}
    medqa = results.get("medqa") or {}
    rag_quality = results.get("rag_quality") or {}
    medqa_summary = "MedQA was not completed because the configured LLM credentials were not accepted by the provider." \
        if medqa.get("status") == "failed" else (
            f"Direct LLM accuracy was {percent(medqa.get('accuracy_direct'))}, while RAG-augmented accuracy was "
            f"{percent(medqa.get('accuracy_rag'))}."
            if medqa.get("status") == "completed"
            else "MedQA was not run in this benchmark invocation."
        )
    retrieval_summary = (
        f"Retrieval keyword hit rates were FAISS {percent(rag_quality.get('faiss_keyword_hit_rate'))}, "
        f"BM25 {percent(rag_quality.get('bm25_keyword_hit_rate'))}, and "
        f"Hybrid {percent(rag_quality.get('hybrid_keyword_hit_rate'))}."
        if rag_quality.get("status") == "completed"
        else "Retrieval quality was not run in this benchmark invocation."
    )

    category_rows = []
    for category, row in sorted((medqa.get("by_category") or {}).items()):
        category_rows.append(
            f"| {category.title()} | {percent(row.get('accuracy_direct'))} | {percent(row.get('accuracy_rag'))} |"
        )
    if not category_rows:
        category_rows = ["| N/A | N/A | N/A |"]

    delta_rows = []
    for category, row in sorted((medqa.get("by_category") or {}).items()):
        delta_rows.append(
            f"| {category.title()} | {percent(row.get('accuracy_direct'))} | {percent(row.get('accuracy_rag'))} | {percent(row.get('delta'))} |"
        )
    if not delta_rows:
        delta_rows = ["| N/A | N/A | N/A | N/A |"]

    retrieval_rows = [
        f"| FAISS only | {percent(rag_quality.get('faiss_keyword_hit_rate'))} | {percent(rag_quality.get('faiss_top5_hit_rate'))} | {rag_quality.get('latency_ms_mean', {}).get('faiss', 'N/A')} |",
        f"| BM25 only | {percent(rag_quality.get('bm25_keyword_hit_rate'))} | {percent(rag_quality.get('bm25_top5_hit_rate'))} | {rag_quality.get('latency_ms_mean', {}).get('bm25', 'N/A')} |",
        f"| Hybrid + RRF | {percent(rag_quality.get('hybrid_keyword_hit_rate'))} | {percent(rag_quality.get('hybrid_top5_hit_rate'))} | {rag_quality.get('latency_ms_mean', {}).get('hybrid', 'N/A')} |",
    ]

    return "\n".join(
        [
            "# Benchmark Results",
            "",
            "## Overview",
            f"Clinical GraphRAG Pro was evaluated on {metadata.get('generated_date', 'unknown date')} using {medqa.get('model') or metadata.get('configured_model') or 'the configured provider'}.",
            medqa_summary,
            retrieval_summary,
            "",
            "## MedQA Status",
            "| Category | Direct Accuracy | RAG Accuracy |",
            "| --- | ---: | ---: |",
            *category_rows,
            "",
            "## RAG vs Direct LLM",
            "| Category | Direct Accuracy | RAG Accuracy | Delta |",
            "| --- | ---: | ---: | ---: |",
            *delta_rows,
            "",
            "## Retrieval Quality",
            "| Method | Keyword Hit Rate | Top-5 Hit Rate | Mean Latency (ms) |",
            "| --- | ---: | ---: | ---: |",
            *retrieval_rows,
            "",
            "## Methodology",
            "- Dataset: 100 original clinical MCQ questions",
            "- Split: Cardiology 20, Endocrinology 20, Nephrology 15, Pharmacology/Drug interactions 15, Pulmonology 15, Hematology 15",
            f"- Model: {medqa.get('model') or metadata.get('configured_model') or 'provider unavailable'}",
            "- Temperature: 0 (deterministic)",
            "- RAG: top-3 dense retrieval for MedQA prompt augmentation; top-5 hybrid retrieval with RRF fusion for retrieval-quality scoring",
            "",
            "## Limitations",
            "- Questions are synthetic, not from an official USMLE or MedQA release.",
            f"- Evaluation was conducted on {metadata.get('generated_date', 'unknown date')}; results may vary with different indexed documents.",
            "- The currently indexed retrieval corpus is whatever chunk artifacts were present locally at runtime.",
            "- MedQA requires valid external LLM credentials; if provider auth fails, the benchmark reports that failure instead of fabricating accuracy.",
            "- Retrieval hit-rate scoring is keyword based and does not replace physician review of answer quality.",
            "",
        ]
    )


def print_summary(results: dict[str, Any]) -> None:
    metadata = results.get("metadata") or {}
    medqa = results.get("medqa") or {}
    rag_quality = results.get("rag_quality") or {}
    category_rows = medqa.get("by_category") or {}
    improvement = None
    if medqa.get("accuracy_direct") is not None and medqa.get("accuracy_rag") is not None:
        improvement = (medqa["accuracy_rag"] - medqa["accuracy_direct"]) * 100

    print("=== CLINICAL GRAPHRAG PRO — BENCHMARK RESULTS ===")
    print(f"Date: {metadata.get('generated_date', 'unknown')}")
    print(f"Model: {medqa.get('model') or metadata.get('configured_model') or 'unknown'}")
    print(f"Questions evaluated: {medqa.get('questions_evaluated', 0)}")
    print("")
    print("MedQA Accuracy:")
    if medqa.get("status") == "completed":
        print(f"  Direct LLM (no RAG):  {percent(medqa.get('accuracy_direct'))}")
        improvement_text = f"  RAG-augmented:        {percent(medqa.get('accuracy_rag'))}"
        if improvement is not None:
            improvement_text += f"  ({improvement:+.1f}% improvement)"
        print(improvement_text)
    elif medqa.get("status") == "failed":
        print("  Direct LLM (no RAG):  N/A")
        print("  RAG-augmented:        N/A")
        print(f"  Error:                {medqa.get('error')}")
    else:
        print("  Not run")
    print("")
    print("By category:")
    if category_rows:
        for category in ["cardiology", "endocrinology", "nephrology", "pharmacology", "pulmonology", "hematology"]:
            row = category_rows.get(category)
            if not row:
                continue
            print(
                f"  {category.title():<16} {percent(row.get('accuracy_direct'))} direct -> {percent(row.get('accuracy_rag'))} RAG"
            )
    else:
        print("  N/A")
    print("")
    print("RAG Retrieval Quality:")
    if rag_quality.get("status") == "completed":
        print(f"  Keyword hit rate (FAISS only):    {percent(rag_quality.get('faiss_keyword_hit_rate'))}")
        print(f"  Keyword hit rate (BM25 only):     {percent(rag_quality.get('bm25_keyword_hit_rate'))}")
        print(f"  Keyword hit rate (Hybrid+RRF):    {percent(rag_quality.get('hybrid_keyword_hit_rate'))}")
        print(
            "  Mean retrieval latency:           "
            f"{rag_quality.get('latency_ms_mean', {}).get('hybrid', 'N/A')} ms"
        )
    elif rag_quality.get("status") == "failed":
        print(f"  Error: {rag_quality.get('error')}")
    else:
        print("  Not run")
    print("")
    print("Latency:")
    print(f"  Mean response time (no RAG):      {seconds_from_ms(medqa.get('latency_direct_ms_mean'))}")
    print(f"  Mean response time (with RAG):    {seconds_from_ms(medqa.get('latency_rag_ms_mean'))}")
    print(f"  95th percentile:                  {seconds_from_ms(medqa.get('latency_p95_ms'))}")


async def main() -> int:
    args = parse_args()
    if not MEDQA_PATH.exists():
        raise FileNotFoundError(f"Missing benchmark dataset: {MEDQA_PATH}")
    if not RETRIEVAL_PATH.exists():
        raise FileNotFoundError(f"Missing retrieval benchmark dataset: {RETRIEVAL_PATH}")

    output_path = args.output if args.output.is_absolute() else (REPO_ROOT / args.output)
    output_path = output_path.resolve()
    markdown_path = DEFAULT_MARKDOWN_PATH if output_path == DEFAULT_OUTPUT_PATH else output_path.parent / "BENCHMARK.md"

    existing = load_existing_results(output_path)
    results = existing if isinstance(existing, dict) else ensure_output_shell(output_path)

    runtime, temp_dir = build_corpus_runtime()
    results["metadata"]["generated_at"] = datetime.now(timezone.utc).isoformat()
    results["metadata"]["generated_date"] = results["metadata"]["generated_at"][:10]
    results["metadata"]["requested_mode"] = args.mode
    results["metadata"]["requested_questions"] = args.n
    results["metadata"]["output_path"] = str(output_path.relative_to(REPO_ROOT))
    results["metadata"]["configured_provider"] = get_settings().llm_provider
    results["metadata"]["configured_model"] = (
        get_settings().groq_model if get_settings().llm_provider.lower() == "groq" else get_settings().gemini_model
    )
    results["corpus"] = {
        "chunk_count": runtime.chunk_count,
        "document_count": runtime.document_count,
        "source_paths": runtime.source_paths,
        "embedding_model": runtime.embedding_model,
        "embedding_load_ms": runtime.embedding_load_ms,
        "effective_embedding_dim": runtime.effective_embedding_dim,
    }
    save_json(output_path, results)

    exit_code = 0
    try:
        if args.mode in {"medqa", "all"}:
            await run_medqa(
                n=args.n,
                runtime=runtime,
                results=results,
                output_path=output_path,
            )
            if results["medqa"]["status"] == "failed":
                exit_code = 1

        if args.mode in {"rag_quality", "all"}:
            await run_retrieval_quality(
                runtime=runtime,
                results=results,
                output_path=output_path,
            )
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
        await llm_service.close()

    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(benchmark_markdown(results), encoding="utf-8")
    save_json(output_path, results)
    print_summary(results)
    print("")
    print(f"Saved JSON: {output_path.relative_to(REPO_ROOT)}")
    print(f"Saved Markdown: {markdown_path.relative_to(REPO_ROOT)}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
