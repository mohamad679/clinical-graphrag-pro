import pytest
from app.services.evaluation import evaluation_service, EvalResult

@pytest.mark.asyncio
async def test_eval_result_properties_and_payload():
    """Verify all convenience property mappings and the metric payload on EvalResult."""
    result = EvalResult(
        query="What is the treatment for pneumonia?",
        answer="Pneumonia is treated with Ceftriaxone [chunk-1].",
        answer_groundedness=0.9,
        citation_correctness=1.0,
        retrieval_precision=0.8,
        retrieval_recall_proxy=0.85,
        clinician_acceptance_rate=1.0,
        hallucination_rate=0.1,
        overall_score=0.92,
        details={"answer_relevancy": {"score": 0.88}}
    )
    
    # Test property aliases
    assert result.faithfulness == 0.9
    assert result.relevance == 0.88
    assert result.answer_relevancy == 0.88
    assert result.citation_accuracy == 1.0
    assert result.context_precision == 0.8
    assert result.context_recall == 0.85
    
    # Test metric payload
    payload = result.metric_payload()
    assert payload["answer_groundedness"] == 0.9
    assert payload["citation_correctness"] == 1.0
    assert payload["retrieval_precision"] == 0.8
    assert payload["retrieval_recall_proxy"] == 0.85
    assert payload["clinician_acceptance_rate"] == 1.0
    assert payload["hallucination_rate"] == 0.1
    assert payload["overall_score"] == 0.92
    assert payload["faithfulness"] == 0.9
    assert payload["answer_relevancy"] == 0.88
    assert payload["citation_accuracy"] == 1.0
    assert payload["context_precision"] == 0.8
    assert payload["context_recall"] == 0.85
    assert payload["relevance"] == 0.88

@pytest.mark.asyncio
async def test_evaluation_empty_answer_and_missing_tokens():
    """Test evaluation edge cases such as empty answers and missing tokens in relevancy checks."""
    # 1. Test empty answer in answer groundedness (line 199)
    res_empty_ans = await evaluation_service.evaluate(
        query="any query",
        answer="",
        context_chunks=[{"chunk_text": "some context"}]
    )
    assert res_empty_ans.answer_groundedness == 0.0
    
    # 2. Test missing query or answer tokens in relevancy evaluation (line 211)
    res_no_tokens = await evaluation_service.evaluate(
        query="...",  # only non-word characters
        answer="...",
        context_chunks=[{"chunk_text": "some context"}]
    )
    assert res_no_tokens.answer_relevancy == 0.0

@pytest.mark.asyncio
async def test_evaluation_full_run():
    """Verify a normal successful run of the evaluation service."""
    res = await evaluation_service.evaluate(
        query="What is the diagnosis?",
        answer="The patient has diabetes mellitus [c1].",
        context_chunks=[{"chunk_id": "c1", "chunk_text": "Diabetes mellitus is confirmed by high fasting glucose."}],
        expected_answer="Diabetes mellitus.",
        expected_chunk_ids=["c1"]
    )
    assert res.overall_score > 0.0
    assert res.answer_groundedness > 0.0
    assert res.citation_correctness == 1.0
