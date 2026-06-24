import importlib.util
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import query_engine as query_engine_module
from app.services.bm25_index import BM25Index
from app.services.query_engine import QueryEngine
from app.services.vector_store import FAISSBackend, _EmbeddingChunkingMixin


@pytest.fixture
def phase1_env():
    """Avoid unrelated database reset work in these retrieval-only tests."""
    return None


class DeterministicEmbedder:
    def get_sentence_embedding_dimension(self) -> int:
        return int(get_settings().embedding_dim)

    def encode(self, texts, normalize_embeddings: bool = True, **_kwargs):
        if isinstance(texts, str):
            texts = [texts]
        return _EmbeddingChunkingMixin._deterministic_embed(
            list(texts),
            normalize_embeddings=normalize_embeddings,
        )


def _patch_deterministic_dense(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "vector_store_dir", tmp_path / "vectors")
    monkeypatch.setattr(settings, "embedding_model", "deterministic-local")
    monkeypatch.setattr(settings, "embedding_dim", 32)
    monkeypatch.setattr(_EmbeddingChunkingMixin, "_get_embedder", lambda _self: DeterministicEmbedder())


def _build_retrieval_indexes(monkeypatch, tmp_path: Path):
    _patch_deterministic_dense(monkeypatch, tmp_path)
    vector = FAISSBackend()
    sparse = BM25Index(use_database=False)
    scope_a = {"tenant_id": "tenant-a", "patient_id": "patient-1", "user_id": "user-a"}
    scope_b = {"tenant_id": "tenant-b", "patient_id": "patient-2", "user_id": "user-b"}
    chunks_a = [
        {
            "chunk_id": "tenant-a-metformin-c0",
            "chunk_index": 0,
            "text": "Assessment: HbA1c 7.2%. Continue metformin 500mg BID for type 2 diabetes.",
        }
    ]
    chunks_b = [
        {
            "chunk_id": "tenant-b-lisinopril-c0",
            "chunk_index": 0,
            "text": "Assessment: hypertension controlled with lisinopril 10mg daily.",
        }
    ]
    chunks_c = [
        {
            "chunk_id": "tenant-c-warfarin-c0",
            "chunk_index": 0,
            "text": "Assessment: atrial fibrillation treated with warfarin INR monitoring.",
        }
    ]

    vector.add_documents("doc-a", "tenant_a_diabetes.txt", chunks_a[0]["text"], chunks=chunks_a, metadata=scope_a)
    sparse.add_document(chunks_a, "doc-a", "tenant_a_diabetes.txt", user_id="user-a", metadata=scope_a)
    vector.add_documents("doc-b", "tenant_b_hypertension.txt", chunks_b[0]["text"], chunks=chunks_b, metadata=scope_b)
    sparse.add_document(chunks_b, "doc-b", "tenant_b_hypertension.txt", user_id="user-b", metadata=scope_b)
    vector.add_documents(
        "doc-c",
        "tenant_c_anticoagulation.txt",
        chunks_c[0]["text"],
        chunks=chunks_c,
        metadata={"tenant_id": "tenant-c", "patient_id": "patient-3", "user_id": "user-c"},
    )
    sparse.add_document(
        chunks_c,
        "doc-c",
        "tenant_c_anticoagulation.txt",
        user_id="user-c",
        metadata={"tenant_id": "tenant-c", "patient_id": "patient-3", "user_id": "user-c"},
    )
    return vector, sparse, scope_a, scope_b


def _load_evaluator_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "evaluate_retrieval.py"
    spec = importlib.util.spec_from_file_location("evaluate_retrieval_module", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_bm25_index_not_empty_after_ingestion(phase1_env):
    bm25 = BM25Index(use_database=False)
    bm25.add_document(
        [{"chunk_id": "c1", "text": "Continue apixaban 5mg BID for atrial fibrillation."}],
        "doc-1",
        "anticoagulation.txt",
        user_id="user-1",
        metadata={"tenant_id": "tenant-1", "patient_id": "patient-1"},
    )

    stats = bm25.get_stats()
    assert stats["total_documents"] == 1
    assert stats["token_count"] > 0
    assert stats["vocabulary_size"] > 0
    assert stats["empty_document_count"] == 0


def test_exact_clinical_keyword_query_returns_correct_chunk(phase1_env):
    bm25 = BM25Index(use_database=False)
    bm25.add_document(
        [{"chunk_id": "metformin-c0", "text": "Plan: continue metformin 500mg BID after HbA1c review."}],
        "doc-metformin",
        "diabetes.txt",
        user_id="user-1",
        metadata={"tenant_id": "tenant-1", "patient_id": "patient-1"},
    )
    bm25.add_document(
        [{"chunk_id": "lisinopril-c0", "text": "Plan: continue lisinopril 10mg daily."}],
        "doc-lisinopril",
        "hypertension.txt",
        user_id="user-1",
        metadata={"tenant_id": "tenant-1", "patient_id": "patient-1"},
    )
    bm25.add_document(
        [{"chunk_id": "warfarin-c0", "text": "Plan: monitor warfarin and INR weekly."}],
        "doc-warfarin",
        "anticoagulation.txt",
        user_id="user-1",
        metadata={"tenant_id": "tenant-1", "patient_id": "patient-1"},
    )

    results = bm25.search("metformin 500mg", filters={"tenant_id": "tenant-1", "patient_id": "patient-1"})
    assert results[0]["chunk_id"] == "metformin-c0"


def test_medical_abbreviations_and_dosage_tokens_survive_normalization(phase1_env):
    tokens = BM25Index._tokenize("HbA1c 7.2%, Na+ 132 mmol/L, apixaban 5mg BID, qHS.")
    assert "hba1c" in tokens
    assert "na+" in tokens
    assert "mmol/l" in tokens
    assert "5mg" in tokens
    assert "bid" in tokens
    assert "qhs" in tokens


def test_dense_and_sparse_results_use_compatible_chunk_ids(monkeypatch, tmp_path, phase1_env):
    vector, sparse, scope_a, _scope_b = _build_retrieval_indexes(monkeypatch, tmp_path)

    dense_results = vector.search("metformin 500mg", top_k=1, filters=scope_a)
    sparse_results = sparse.search("metformin 500mg", top_k=1, filters=scope_a)

    assert dense_results
    assert sparse_results
    assert dense_results[0].chunk_id == sparse_results[0]["chunk_id"] == "tenant-a-metformin-c0"


def test_rrf_combines_dense_and_sparse_candidates_correctly(phase1_env):
    candidates = [
        {"chunk_id": "dense-only", "vector_ranks": [0], "bm25_ranks": []},
        {"chunk_id": "both", "vector_ranks": [1], "bm25_ranks": [0]},
        {"chunk_id": "sparse-only", "vector_ranks": [], "bm25_ranks": [1]},
    ]

    merged = QueryEngine()._rrf_merge(candidates)

    assert merged[0]["chunk_id"] == "both"
    assert merged[0]["score"] > merged[1]["score"]


def test_scope_filtering_applies_identically_to_bm25_and_faiss(monkeypatch, tmp_path, phase1_env):
    vector, sparse, scope_a, scope_b = _build_retrieval_indexes(monkeypatch, tmp_path)

    dense_a = vector.search("metformin", top_k=5, filters=scope_a)
    sparse_a = sparse.search("metformin", top_k=5, filters=scope_a)
    dense_b = vector.search("lisinopril", top_k=5, filters=scope_b)
    sparse_b = sparse.search("lisinopril", top_k=5, filters=scope_b)
    dense_cross_scope = vector.search("metformin", top_k=5, filters=scope_b)
    sparse_cross_scope = sparse.search("metformin", top_k=5, filters=scope_b)

    assert [result.chunk_id for result in dense_a] == ["tenant-a-metformin-c0"]
    assert [result["chunk_id"] for result in sparse_a] == ["tenant-a-metformin-c0"]
    assert [result.chunk_id for result in dense_b] == ["tenant-b-lisinopril-c0"]
    assert [result["chunk_id"] for result in sparse_b] == ["tenant-b-lisinopril-c0"]
    assert all(result.chunk_id != "tenant-a-metformin-c0" for result in dense_cross_scope)
    assert sparse_cross_scope == []


def test_cross_tenant_sparse_retrieval_is_blocked(monkeypatch, tmp_path, phase1_env):
    _vector, sparse, _scope_a, scope_b = _build_retrieval_indexes(monkeypatch, tmp_path)

    results = sparse.search("metformin 500mg", top_k=5, filters=scope_b)

    assert results == []


@pytest.mark.asyncio
async def test_hybrid_retrieval_fails_loudly_when_bm25_empty(monkeypatch, tmp_path, phase1_env):
    _patch_deterministic_dense(monkeypatch, tmp_path)
    vector = FAISSBackend()
    scope = {"tenant_id": "tenant-a", "patient_id": "patient-1", "user_id": "user-a"}
    vector.add_documents(
        "doc-a",
        "tenant_a_diabetes.txt",
        "Continue metformin 500mg BID.",
        chunks=[{"chunk_id": "tenant-a-metformin-c0", "chunk_index": 0, "text": "Continue metformin 500mg BID."}],
        metadata=scope,
    )
    empty_sparse = BM25Index(use_database=False)

    monkeypatch.setattr(query_engine_module, "vector_store_service", vector)
    monkeypatch.setattr(query_engine_module, "bm25_index", empty_sparse)

    with pytest.raises(RuntimeError, match="BM25 sparse index is empty"):
        await QueryEngine().query("metformin", top_k=1, mode="hybrid", filters=scope)


@pytest.mark.asyncio
async def test_hybrid_trace_includes_sparse_fusion_and_reranker_metadata(monkeypatch, tmp_path, phase1_env):
    vector, sparse, scope_a, _scope_b = _build_retrieval_indexes(monkeypatch, tmp_path)

    monkeypatch.setattr(query_engine_module, "vector_store_service", vector)
    monkeypatch.setattr(query_engine_module, "bm25_index", sparse)
    reranker_module = __import__("app.services.reranker", fromlist=["RankedResult", "RerankResult"])
    monkeypatch.setattr(
        query_engine_module.reranker_service,
        "rerank_with_metadata",
        lambda query, candidates, top_k, patient_id=None, tenant_id=None: reranker_module.RerankResult(
            items=[
                reranker_module.RankedResult(
                    chunk_text=c["chunk_text"],
                    chunk_index=c["chunk_index"],
                    document_id=c["document_id"],
                    document_name=c["document_name"],
                    original_score=c.get("score", 0.0),
                    rerank_score=c.get("score", 0.0),
                    chunk_id=c.get("chunk_id", ""),
                )
                for c in candidates[:top_k]
            ],
            applied=False,
            model_loaded=False,
            fallback_reason="model_unavailable:test",
            latency_ms=0.0,
        ),
    )

    response = await QueryEngine().query(
        "metformin 500mg",
        top_k=1,
        mode="hybrid_rerank",
        filters=scope_a,
        trace=True,
    )

    trace = response.trace_info
    assert trace["rrf_input_lists"]["dense_rankings"]
    assert trace["rrf_input_lists"]["sparse_rankings"]
    assert trace["fusion_output_ranking"]
    assert trace["reranker_applied"] is False
    assert trace["reranker_model_loaded"] is False
    assert trace["reranker_fallback_reason"] == "model_unavailable:test"


def test_benchmark_artifact_contract_and_markdown_summary(phase1_env):
    evaluator = _load_evaluator_module()
    payload = {
        "artifact_schema_version": evaluator.ARTIFACT_SCHEMA_VERSION,
        "artifact_type": "retrieval_quality_benchmark",
        "metadata": {
            "timestamp": "20260606T000000Z",
            "seed": 20260605,
            "benchmark_category": "retrieval-quality benchmark",
            "note": "Synthetic retrieval regression benchmark; not clinical validation.",
        },
        "dataset": {
            "path": "backend/data/synthetic_clinical_qa_180.jsonl",
            "sha256": "abc",
            "line_count": 1,
            "query_count": 1,
            "skipped_abstention_only_cases": 0,
        },
        "code": {
            "git_commit": "abc",
            "git_branch": "main",
            "working_tree_status_sha256_16": "def",
            "working_tree_dirty_entries": 0,
        },
        "configuration": {"embedding_model": "deterministic-local"},
        "corpus_statistics": {
            "chunk_count": 1,
            "bm25_stats": {"token_count": 5, "vocabulary_size": 5},
        },
        "runtime": {"python": "3.12", "platform": "test", "executable": "python"},
        "backend_mode": {"mode": "test", "dense_backend": "faiss", "sparse_backend": "memory-rank-bm25"},
        "results": {},
    }
    for method in evaluator.METHODS:
        payload["results"][method] = {
            "latency_mean": 1.0,
            "latency_p50": 1.0,
            "latency_p95": 1.0,
            "latency_p99": 1.0,
            "mrr": 1.0,
            "precision_at_1": 1.0,
            "recall_at_1": 1.0,
            "recall_at_3": 1.0,
            "recall_at_5": 1.0,
            "ndcg_at_5": 1.0,
            "zero_result_rate": 0.0,
            "failure_counts": {
                "no_results": 0,
                "no_relevant_at_5": 0,
                "exceptions": 0,
                "empty_index_failures": 0,
                "authorization_filter_rejection_count": 0,
            },
            "candidate_counts": {
                "dense_mean": 1.0,
                "sparse_mean": 1.0,
                "merged_mean": 1.0,
                "reranked_query_count": 0,
            },
        }

    evaluator.validate_artifact_payload(payload)
    markdown = evaluator.render_markdown_summary(payload)
    assert "not clinical validation" in markdown.lower()
    assert "p99 ms" in markdown
