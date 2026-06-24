"""
Phase 4 retrieval and performance stabilization tests.
Run with: pytest --noconftest backend/tests/test_phase4_retrieval.py -q
"""

import pytest

from app.services.vector_store import SearchResult
from app.services import query_engine as query_engine_module
from app.services.bm25_index import BM25Index
from app.services.rag import ContextBundle, rag_service


@pytest.mark.asyncio
async def test_query_engine_vector_only_sorts_by_vector_score(monkeypatch):
    def fake_vector_search(query: str, top_k: int = 5, filters: dict | None = None):
        return [
            SearchResult("chunk-low", 0, "doc-low", "Low", 0.20),
            SearchResult("chunk-high", 1, "doc-high", "High", 0.95),
        ]

    monkeypatch.setattr(query_engine_module.vector_store_service, "search", fake_vector_search)
    monkeypatch.setattr(query_engine_module.bm25_index, "search", lambda *_args, **_kwargs: [])

    result = await query_engine_module.query_engine.query(
        "hypertension treatment",
        top_k=2,
        use_hybrid=False,
        use_reranking=False,
        expand_query=False,
        allow_unfiltered=True,
    )

    assert len(result.results) == 2
    assert result.results[0]["document_id"] == "doc-high"
    assert result.results[0]["score"] >= result.results[1]["score"]


@pytest.mark.asyncio
async def test_query_engine_hybrid_uses_bm25_and_vector_ranks(monkeypatch):
    def fake_vector_search(query: str, top_k: int = 5, filters: dict | None = None):
        return [
            SearchResult("chunk-a", 0, "doc-a", "A", 0.90),
            SearchResult("chunk-b", 0, "doc-b", "B", 0.70),
        ]

    def fake_bm25_search(query: str, top_k: int = 5, filters: dict | None = None):
        return [
            {"chunk_text": "chunk-b", "chunk_index": 0, "document_id": "doc-b", "document_name": "B", "score": 6.2},
        ]

    async def fake_bm25_stats():
        return {"total_documents": 1, "active_documents": 1, "index_loaded": True}

    monkeypatch.setattr(query_engine_module.vector_store_service, "search", fake_vector_search)
    monkeypatch.setattr(query_engine_module.bm25_index, "search", fake_bm25_search)
    monkeypatch.setattr(query_engine_module.bm25_index, "get_stats_async", fake_bm25_stats)

    result = await query_engine_module.query_engine.query(
        "drug interaction",
        top_k=2,
        use_hybrid=True,
        use_reranking=False,
        expand_query=False,
        allow_unfiltered=True,
    )

    assert len(result.results) == 2
    # doc-b appears in both rankings, so it should win with higher fused score.
    assert result.results[0]["document_id"] == "doc-b"


@pytest.mark.asyncio
async def test_query_engine_forwards_user_filter_to_dense_and_sparse(monkeypatch):
    captured = {"filters": None, "user_id": None}

    def fake_vector_search(query: str, top_k: int = 5, filters: dict | None = None):
        captured["filters"] = filters
        return [SearchResult("chunk-a", 0, "doc-a", "A", 0.9)]

    def fake_bm25_search(query: str, top_k: int = 5, user_id: str | None = None, filters: dict | None = None):
        captured["user_id"] = user_id or (filters.get("user_id") if filters else None)
        return [{"chunk_text": "chunk-a", "chunk_index": 0, "document_id": "doc-a", "document_name": "A", "score": 2.0}]

    async def fake_bm25_stats():
        return {"total_documents": 1, "active_documents": 1, "index_loaded": True}

    monkeypatch.setattr(query_engine_module.vector_store_service, "search", fake_vector_search)
    monkeypatch.setattr(query_engine_module.bm25_index, "search", fake_bm25_search)
    monkeypatch.setattr(query_engine_module.bm25_index, "get_stats_async", fake_bm25_stats)

    await query_engine_module.query_engine.query(
        "authorized search",
        top_k=1,
        use_hybrid=True,
        use_reranking=False,
        expand_query=False,
        user_id="user-123",
    )

    assert captured["filters"] == {"user_id": "user-123"}
    assert captured["user_id"] == "user-123"


def test_bm25_index_search_filters_deleted_documents(monkeypatch):
    bm25 = BM25Index()
    bm25._corpus = [["alpha"], ["beta"]]
    bm25._metadata = [
        {"chunk_text": "alpha text", "chunk_index": 0, "document_id": "doc-a", "document_name": "A"},
        {"chunk_text": "beta text", "chunk_index": 0, "document_id": "doc-b", "document_name": "B"},
    ]
    bm25._deleted_document_ids = set()

    class DummyIndex:
        def get_scores(self, _tokens):
            return [10.0, 9.0]

    bm25._index = DummyIndex()
    monkeypatch.setattr(bm25, "_save_deleted_documents", lambda: None)

    removed = bm25.mark_document_deleted("doc-a")
    assert removed == 1

    results = bm25.search("alpha beta", top_k=2)
    assert len(results) == 1
    assert results[0]["document_id"] == "doc-b"


@pytest.mark.asyncio
async def test_rag_service_returns_guardrail_when_no_grounded_context():
    bundle = ContextBundle(
        mode="retrieval",
        query="unsupported question",
        expanded_queries=[],
        items=[],
        context_text="",
        reasoning_steps=[],
        retrieval_method="hybrid",
        total_candidates=0,
        retrieval_latency_ms=0.0,
        context_policy={"top_k": 5},
    )

    result = await rag_service.generate_answer(question="unsupported question", bundle=bundle)

    assert result.clinician_review_required is True
    assert "not have enough evidence" in result.answer.lower()
    assert result.confidence_score == 0.0
