import pytest
from unittest.mock import MagicMock, patch
from app.services.reranker import RerankerService

def test_rerank_empty_candidates():
    service = RerankerService()
    results = service.rerank("query", [])
    assert results == []

def test_rerank_model_load_failure():
    service = RerankerService()
    # Force _get_model to raise an exception to simulate failure
    with patch.object(service, "_get_model", side_effect=Exception("Failed to load cross encoder")):
        candidates = [
            {
                "chunk_text": "text1",
                "chunk_index": 0,
                "document_id": "doc1",
                "document_name": "doc1.txt",
                "score": 0.8,
                "chunk_id": "c1"
            },
            {
                "chunk_text": "text2",
                "chunk_index": 1,
                "document_id": "doc2",
                "document_name": "doc2.txt",
                "score": 0.7,
                "chunk_id": "c2"
            }
        ]
        results = service.rerank("query", candidates, top_k=1)
        assert len(results) == 1
        assert results[0].chunk_text == "text1"
        assert results[0].original_score == 0.8
        assert results[0].rerank_score == 0.8

def test_rerank_model_load_failure_exposes_metadata():
    service = RerankerService()
    with patch.object(service, "_get_model", side_effect=RuntimeError("offline")):
        result = service.rerank_with_metadata(
            "query",
            [
                {
                    "chunk_text": "text1",
                    "chunk_index": 0,
                    "document_id": "doc1",
                    "document_name": "doc1.txt",
                    "score": 0.8,
                    "chunk_id": "c1",
                }
            ],
            top_k=1,
        )

    assert result.items[0].chunk_id == "c1"
    assert result.applied is False
    assert result.model_loaded is False
    assert result.fallback_reason == "model_unavailable:RuntimeError"

def test_rerank_import_error():
    service = RerankerService()
    # Mock sys.modules or standard imports
    with patch("sentence_transformers.CrossEncoder", side_effect=ImportError("No module sentence_transformers")):
        with pytest.raises(ImportError):
            service._get_model()

def test_rerank_successful_flow():
    service = RerankerService()
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.15, 0.95]
    
    with patch.object(service, "_get_model", return_value=mock_model):
        candidates = [
            {
                "chunk_text": "text1",
                "chunk_index": 0,
                "document_id": "doc1",
                "document_name": "doc1.txt",
                "score": 0.8,
                "chunk_id": "c1"
            },
            {
                "chunk_text": "text2",
                "chunk_index": 1,
                "document_id": "doc2",
                "document_name": "doc2.txt",
                "score": 0.7,
                "chunk_id": "c2"
            }
        ]
        results = service.rerank("query", candidates, top_k=2)
        # Should sort by rerank_score descending (index 1 has rerank score 0.95, index 0 has 0.15)
        assert len(results) == 2
        assert results[0].chunk_text == "text2"
        assert results[0].rerank_score == 0.95
        assert results[1].chunk_text == "text1"
        assert results[1].rerank_score == 0.15
        mock_model.predict.assert_called_once_with([("query", "text1"), ("query", "text2")])
