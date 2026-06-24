import pytest
from app.services.rag import RAGService, ContextBundle, ContextItem

@pytest.mark.asyncio
async def test_rag_abstention_on_empty_context():
    """Verify that an empty context bundle immediately returns the required safe abstention response."""
    rag_service = RAGService()
    bundle = ContextBundle(
        mode="retrieval",
        query="What is the dosage of Azithromycin?",
        expanded_queries=[],
        items=[],
        context_text="",
        reasoning_steps=[],
        retrieval_method="vector",
        total_candidates=0,
        retrieval_latency_ms=0.0,
        context_policy={}
    )
    
    response = await rag_service.generate_answer(
        question="What is the dosage of Azithromycin?",
        bundle=bundle
    )
    
    assert "I do not have enough evidence in the provided documents to answer this safely." in response.answer
    assert response.confidence_score == 0.0
    assert response.clinician_review_required is True

@pytest.mark.asyncio
async def test_rag_abstention_on_low_scores():
    """Verify that a bundle where the highest chunk relevance score is < 0.35 triggers safe abstention."""
    rag_service = RAGService()
    
    # Items with low scores
    low_score_item = ContextItem(
        citation_id="SRC1",
        chunk_id="c1",
        document_id="doc1",
        document_name="pneumonia.txt",
        chunk_index=0,
        chunk_text="A brief sentence about pneumonia diagnosis.",
        retrieval_score=0.25, # < 0.35
        reranker_score=0.20   # < 0.35
    )
    
    bundle = ContextBundle(
        mode="retrieval",
        query="What is the dosage of Azithromycin?",
        expanded_queries=[],
        items=[low_score_item],
        context_text="[SRC1] A brief sentence about pneumonia diagnosis.",
        reasoning_steps=[],
        retrieval_method="vector",
        total_candidates=1,
        retrieval_latency_ms=0.0,
        context_policy={}
    )
    
    response = await rag_service.generate_answer(
        question="What is the dosage of Azithromycin?",
        bundle=bundle
    )
    
    assert "I do not have enough evidence in the provided documents to answer this safely." in response.answer
    assert response.confidence_score == 0.0
    assert response.clinician_review_required is True

def test_calculate_safe_confidence():
    """Test confidence calculation behavior with matching/missing citations and low vector scores."""
    rag_service = RAGService()
    
    item1 = ContextItem(
        citation_id="SRC1",
        chunk_id="c1",
        document_id="doc1",
        document_name="doc.txt",
        chunk_index=0,
        chunk_text="Patient has pneumonia.",
        retrieval_score=0.8,
        reranker_score=0.85
    )
    
    bundle = ContextBundle(
        mode="retrieval",
        query="query",
        expanded_queries=[],
        items=[item1],
        context_text="text",
        reasoning_steps=[],
        retrieval_method="vector",
        total_candidates=1,
        retrieval_latency_ms=0.0,
        context_policy={}
    )
    
    # Case 1: No citations in answer -> confidence should be 0.0
    conf_no_citations = rag_service.calculate_safe_confidence(0.9, bundle, "Patient has pneumonia without citation.")
    assert conf_no_citations == 0.0
    
    # Case 2: Matching valid citation -> confidence should be calculated correctly
    conf_valid = rag_service.calculate_safe_confidence(0.9, bundle, "Patient has pneumonia [SRC1].")
    # expected: (0.3 * 0.9 + 0.7 * 0.85) * (1.0) = 0.27 + 0.595 = 0.865 -> 0.86
    assert conf_valid == 0.86
    
    # Case 3: Invalid citation -> confidence should be 0.0
    conf_invalid = rag_service.calculate_safe_confidence(0.9, bundle, "Patient has pneumonia [SRC2].")
    assert conf_invalid == 0.0
    
    # Case 4: Answer contains abstention text -> confidence should be 0.0
    conf_abstain = rag_service.calculate_safe_confidence(0.9, bundle, "I do not have enough evidence in the provided documents to answer this safely.")
    assert conf_abstain == 0.0
