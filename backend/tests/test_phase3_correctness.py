"""
Phase 3 correctness and data-integrity focused unit tests.
Run with: pytest --noconftest backend/tests/test_phase3_correctness.py -q
"""

import numpy as np
import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatFeedback
from app.services.vector_store import VectorStoreService


def _build_test_service(monkeypatch) -> VectorStoreService:
    svc = VectorStoreService()
    svc._chunks = [
        {
            "chunk_id": "c1",
            "chunk_text": "alpha",
            "chunk_index": 0,
            "document_id": "doc-a",
            "document_name": "A",
        },
        {
            "chunk_id": "c2",
            "chunk_text": "beta",
            "chunk_index": 1,
            "document_id": "doc-a",
            "document_name": "A",
        },
        {
            "chunk_id": "c3",
            "chunk_text": "gamma",
            "chunk_index": 0,
            "document_id": "doc-b",
            "document_name": "B",
        },
    ]
    svc._deleted_document_ids = set()
    svc._rebuild_lookup()

    class DummyIndex:
        ntotal = 3

        def search(self, _embedding, k):
            base_scores = [0.99, 0.88, 0.77]
            base_indices = [0, 1, 2]
            pad = max(0, k - len(base_scores))
            scores = np.array([base_scores[:k] + ([0.0] * pad)], dtype=np.float32)
            indices = np.array([base_indices[:k] + ([-1] * pad)], dtype=np.int64)
            return scores, indices

    class DummyEmbedder:
        def encode(self, *_args, **_kwargs):
            return np.array([[1.0, 0.0, 0.0]], dtype=np.float32)

    monkeypatch.setattr(svc, "_get_index", lambda: DummyIndex())
    monkeypatch.setattr(svc, "_get_embedder", lambda: DummyEmbedder())
    monkeypatch.setattr(svc, "_save_deleted_documents", lambda: None)
    return svc


def test_chat_feedback_accepts_valid_rating():
    fb = ChatFeedback(rating=5, comment="Great")
    assert fb.rating == 5


def test_chat_feedback_rejects_out_of_range_rating():
    with pytest.raises(ValidationError):
        ChatFeedback(rating=0, comment="Invalid")


def test_vector_store_can_fetch_chunks_by_document(monkeypatch):
    svc = _build_test_service(monkeypatch)
    doc_chunks = svc.get_chunks_for_document("doc-a")
    assert len(doc_chunks) == 2
    assert all(c["document_id"] == "doc-a" for c in doc_chunks)


def test_vector_store_deletion_tombstones_document(monkeypatch):
    svc = _build_test_service(monkeypatch)
    removed = svc.mark_document_deleted("doc-a")
    assert removed == 2
    assert svc.get_chunks_for_document("doc-a") == []
    assert all(c["document_id"] != "doc-a" for c in svc.get_all_chunks())


def test_vector_store_search_skips_deleted_documents(monkeypatch):
    svc = _build_test_service(monkeypatch)
    svc.mark_document_deleted("doc-a")
    results = svc.search("question", top_k=2)
    assert len(results) == 1
    assert results[0].document_id == "doc-b"
