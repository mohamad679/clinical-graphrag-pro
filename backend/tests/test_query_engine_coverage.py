import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.query_engine import QueryEngine
from app.services.vector_store import SearchResult
from app.services.bm25_index import BM25Index
from app.services.reranker import RankedResult, RerankResult

@pytest.mark.asyncio
async def test_query_engine_full_hybrid_rerank_flow():
    """Test QueryEngine with hybrid search, query expansion, and reranking fully active using mocks."""
    engine = QueryEngine()
    
    # 1. Mock vector store search
    mock_vector = MagicMock()
    mock_vector.search.return_value = [
        SearchResult(
            chunk_text="Patient has community acquired pneumonia, treated with Ceftriaxone.",
            chunk_index=0,
            document_id="doc-1",
            document_name="pneumonia.txt",
            score=0.9,
            chunk_id="t1-c1"
        )
    ]
    
    # 2. Mock BM25 index search
    mock_bm25 = MagicMock()
    mock_bm25.search.return_value = [
        {
            "chunk_id": "t1-c1",
            "chunk_text": "Patient has community acquired pneumonia, treated with Ceftriaxone.",
            "chunk_index": 0,
            "document_id": "doc-1",
            "document_name": "pneumonia.txt",
            "score": 12.5
        }
    ]
    
    # 3. Mock LLM for query expansion
    mock_generate = AsyncMock(return_value="alternative query 1\nalternative query 2")
    
    # 4. Mock Reranker
    mock_rerank = MagicMock()
    mock_rerank.return_value = RerankResult(
        items=[
            RankedResult(
                chunk_text="Patient has community acquired pneumonia, treated with Ceftriaxone.",
                chunk_index=0,
                document_id="doc-1",
                document_name="pneumonia.txt",
                original_score=0.9,
                rerank_score=0.98,
                chunk_id="t1-c1",
            )
        ],
        applied=True,
        model_loaded=True,
        fallback_reason=None,
        latency_ms=1.0,
    )
    
    with (
        patch("app.services.query_engine.vector_store_service", mock_vector),
        patch("app.services.query_engine.bm25_index", mock_bm25),
        patch("app.services.llm.llm_service.generate", mock_generate),
        patch("app.services.query_engine.reranker_service.rerank_with_metadata", mock_rerank),
    ):
        res = await engine.query(
            query="pneumonia treatment",
            top_k=2,
            use_reranking=True,
            expand_query=True,
            use_hybrid=True,
            user_id="tenant-1"
        )
        
        # Verify calls
        mock_generate.assert_called_once()
        mock_vector.search.assert_called()
        mock_bm25.search.assert_called()
        mock_rerank.assert_called_once()
        
        # Verify merged result
        assert len(res.results) == 1
        assert res.results[0]["chunk_id"] == "t1-c1"
        assert res.results[0]["score"] == 0.98
        assert res.results[0]["original_score"] == 0.9
        assert res.reranked is True
        assert res.retrieval_method == "hybrid"
        assert len(res.expanded_queries) == 2
        assert res.expanded_queries[0] == "alternative query 1"

@pytest.mark.asyncio
async def test_query_engine_expansion_and_reranking_failures():
    """Verify that QueryEngine falls back gracefully when query expansion or reranking fail."""
    engine = QueryEngine()
    
    # 1. Mock vector store search
    mock_vector = MagicMock()
    mock_vector.search.return_value = [
        SearchResult(
            chunk_text="lupus test context",
            chunk_index=0,
            document_id="doc-2",
            document_name="lupus.txt",
            score=0.85,
            chunk_id="t2-c1"
        )
    ]
    
    # 2. Mock BM25 search
    mock_bm25 = MagicMock()
    mock_bm25.search.return_value = []
    
    # 3. Mock LLM query expansion to throw an exception
    mock_generate = AsyncMock(side_effect=RuntimeError("LLM offline"))
    
    # 4. Mock Reranker to throw an exception
    mock_rerank = MagicMock(side_effect=Exception("Reranker model load error"))
    
    with (
        patch("app.services.query_engine.vector_store_service", mock_vector),
        patch("app.services.query_engine.bm25_index", mock_bm25),
        patch("app.services.llm.llm_service.generate", mock_generate),
        patch("app.services.query_engine.reranker_service.rerank_with_metadata", mock_rerank),
    ):
        res = await engine.query(
            query="lupus flare meds",
            top_k=2,
            use_reranking=True,
            expand_query=True,
            use_hybrid=True,
            user_id="tenant-2"
        )
        
        # Verify fallbacks: query still executes, reranking fails gracefully back to fusion/vector scores
        assert len(res.results) == 1
        assert res.results[0]["chunk_id"] == "t2-c1"
        assert res.results[0]["score"] > 0.0  # RRF score
        assert res.reranked is False
        assert len(res.expanded_queries) == 0

@pytest.mark.asyncio
async def test_query_engine_empty_candidates():
    """Verify that QueryEngine returns an empty result set when no candidates are retrieved."""
    engine = QueryEngine()
    
    mock_vector = MagicMock()
    mock_vector.search.return_value = []
    
    mock_bm25 = MagicMock()
    mock_bm25.search.return_value = []
    
    with (
        patch("app.services.query_engine.vector_store_service", mock_vector),
        patch("app.services.query_engine.bm25_index", mock_bm25),
    ):
        res = await engine.query(
            query="unmatchable query",
            top_k=5,
            use_reranking=False,
            expand_query=False,
            use_hybrid=True,
            allow_unfiltered=True,
        )
        assert len(res.results) == 0
        assert res.total_candidates == 0
        assert res.reranked is False


@pytest.mark.asyncio
async def test_query_engine_fails_loudly_when_sparse_index_empty():
    engine = QueryEngine()
    mock_vector = MagicMock()
    mock_vector.search.return_value = []
    empty_bm25 = BM25Index(use_database=False)

    with (
        patch("app.services.query_engine.vector_store_service", mock_vector),
        patch("app.services.query_engine.bm25_index", empty_bm25),
    ):
        with pytest.raises(RuntimeError, match="BM25 sparse index is empty"):
            await engine.query(
                query="pneumonia",
                top_k=5,
                mode="hybrid",
                user_id="user-1",
            )

def test_rrf_expanded_query_does_not_over_boost():
    """A chunk appearing only in expanded query variants
    should not outscore a chunk found by the original query."""
    engine = QueryEngine()
    candidates = [
        {
            "chunk_id": "chunk_a",
            "vector_ranks": [0],
            "bm25_ranks": []
        },
        {
            "chunk_id": "chunk_b",
            "vector_ranks": [0, 4],
            "bm25_ranks": []
        }
    ]
    merged = engine._rrf_merge(candidates)
    assert merged[0]["chunk_id"] == "chunk_a"
    assert merged[1]["chunk_id"] == "chunk_b"
    assert merged[0]["score"] > merged[1]["score"]
