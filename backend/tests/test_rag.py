import pytest
from unittest.mock import patch
from app.services.rag import rag_service, ContextBundle, ContextItem
from app.services.llm import llm_service, LLMResponse

@pytest.fixture
def mock_llm_stream():
    # Setup context item and bundle to avoid guardrails/abstention
    item = ContextItem(
        citation_id="SRC1",
        chunk_id="c1",
        document_id="doc1",
        document_name="doc.txt",
        chunk_index=0,
        chunk_text="Amlodipine 5mg daily was prescribed.",
        retrieval_score=0.9,
    )
    
    bundle = ContextBundle(
        mode="retrieval",
        query="test query",
        expanded_queries=[],
        items=[item],
        context_text="[SRC1] Amlodipine 5mg daily was prescribed.",
        reasoning_steps=[],
        retrieval_method="dense",
        total_candidates=1,
        retrieval_latency_ms=0.0,
        context_policy={},
    )
    
    async def mock_build_retrieval_bundle(*args, **kwargs):
        return bundle

    async def mock_generate_with_metadata(*args, **kwargs):
        return LLMResponse(
            text="Amlodipine 5mg daily was prescribed [SRC1]. [CONFIDENCE: 0.95]",
            provider="test",
            model_used="deterministic",
            token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    with patch.object(rag_service, "build_retrieval_bundle", side_effect=mock_build_retrieval_bundle), \
         patch.object(llm_service, "generate_with_metadata", side_effect=mock_generate_with_metadata):
        yield

@pytest.mark.asyncio
async def test_stream_yields_validated_chunks(mock_llm_stream):
    """Verify stream chunks are emitted after safe full-answer generation."""
    rag_service._settings.stream_mode = "safe"
    rag_service._settings.chat_stream_chunk_size = 12
    tokens = []
    async for event in rag_service.query_stream("test query", top_k=5):
        if event["type"] == "token":
            tokens.append(event["content"])
    assert len(tokens) > 1, "Expected multiple token events (real streaming)"
    assert "".join(tokens).startswith("Amlodipine")
    assert all(len(t) <= 12 for t in tokens), "Tokens should use safe chunking"
