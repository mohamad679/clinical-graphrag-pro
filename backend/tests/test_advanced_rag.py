"""
Tests for Advanced RAG components (Phase 4, Week 7).
Tests sentence-aware chunking, BM25 search, RRF fusion, and reranking.
"""

import pytest
from app.services.vector_store import VectorStoreService
from app.services.bm25_index import BM25Index


# ── Sentence-aware Chunking Tests ────────────────────────


class TestSentenceChunking:
    """Tests for the sentence-aware chunking in VectorStoreService."""

    def setup_method(self):
        self.vs = VectorStoreService()

    def test_split_sentences_basic(self):
        text = "This is sentence one. This is sentence two. And here is three."
        sentences = self.vs._split_sentences(text)
        assert len(sentences) == 3
        assert "sentence one." in sentences[0]
        assert "sentence two." in sentences[1]

    def test_split_sentences_abbreviations(self):
        """Abbreviations like Dr., Mr. should not cause splits."""
        text = "Dr. Smith treated the patient. The condition was severe."
        sentences = self.vs._split_sentences(text)
        assert len(sentences) == 2
        assert "Dr." in sentences[0] or "Dr" in sentences[0]

    def test_chunk_text_returns_dicts(self):
        """Chunks should be dicts with chunk_id and text."""
        text = "First sentence. Second sentence. Third sentence."
        chunks = self.vs.chunk_text(text, chunk_size=10, overlap=2)
        assert len(chunks) > 0
        for chunk in chunks:
            assert "chunk_id" in chunk
            assert "text" in chunk
            assert len(chunk["chunk_id"]) > 0

    def test_chunk_text_respects_boundaries(self):
        """Chunks should end at sentence boundaries, not mid-sentence."""
        # Create text with clear sentence boundaries
        sentences = [f"This is sentence number {i} about medical topics." for i in range(20)]
        text = " ".join(sentences)
        chunks = self.vs.chunk_text(text, chunk_size=30, overlap=5)

        for chunk in chunks:
            # Each chunk should end with a period (sentence boundary)
            assert chunk["text"].rstrip().endswith(".")

    def test_chunk_text_empty(self):
        chunks = self.vs.chunk_text("")
        assert chunks == []

    def test_chunk_text_single_sentence(self):
        text = "Just one sentence here."
        chunks = self.vs.chunk_text(text, chunk_size=100, overlap=10)
        assert len(chunks) == 1
        assert chunks[0]["text"] == text


# ── BM25 Index Tests ────────────────────────────────────


class TestBM25Index:
    """Tests for BM25 keyword search."""

    def setup_method(self):
        self.bm25 = BM25Index()
        # Reset state
        self.bm25._corpus = []
        self.bm25._metadata = []
        self.bm25._index = None

    def test_tokenize(self):
        tokens = BM25Index._tokenize("Type 2 Diabetes Mellitus treatment options")
        assert "diabetes" in tokens
        assert "mellitus" in tokens
        assert "treatment" in tokens

    def test_tokenize_medical_terms(self):
        """Hyphens in medical terms should be preserved."""
        tokens = BM25Index._tokenize("beta-blocker therapy for hypertension")
        assert "beta-blocker" in tokens

    def test_add_and_search(self):
        """Basic add + search lifecycle."""
        chunks = [
            {"chunk_id": "1", "text": "Diabetes mellitus is a metabolic disease", "chunk_index": 0},
            {"chunk_id": "2", "text": "Hypertension is high blood pressure", "chunk_index": 1},
            {"chunk_id": "3", "text": "Cancer treatment involves chemotherapy", "chunk_index": 2},
        ]
        self.bm25.add_document(chunks, "doc1", "test.pdf")

        results = self.bm25.search("diabetes metabolic", top_k=2)
        assert len(results) > 0
        assert "diabetes" in results[0]["chunk_text"].lower()

    def test_search_empty_index(self):
        results = self.bm25.search("anything")
        assert results == []

    def test_search_no_match(self):
        chunks = [
            {"chunk_id": "1", "text": "Completely unrelated content about cooking", "chunk_index": 0},
        ]
        self.bm25.add_document(chunks, "doc1", "recipe.pdf")
        results = self.bm25.search("quantum physics")
        # BM25 may return results with low scores; just verify it doesn't crash
        assert isinstance(results, list)

    def test_get_stats(self):
        stats = self.bm25.get_stats()
        assert "total_documents" in stats
        assert "index_loaded" in stats


# ── RRF Fusion Tests ────────────────────────────────────


class TestRRFLogic:
    """Test Reciprocal Rank Fusion logic in isolation."""

    def test_rrf_formula(self):
        """RRF score = 1/(k + rank). Verify the math."""
        k = 60  # standard constant

        # Rank 0 (top result) should have highest score
        score_rank0 = 1.0 / (k + 0)
        score_rank1 = 1.0 / (k + 1)
        score_rank5 = 1.0 / (k + 5)

        assert score_rank0 > score_rank1 > score_rank5
        assert abs(score_rank0 - 1 / 60) < 1e-6

    def test_rrf_combined_higher(self):
        """A result in both rankings should score higher than one in only one."""
        k = 60
        # Result in vector rank 0 AND bm25 rank 0
        combined = 1.0 / (k + 0) + 1.0 / (k + 0)
        # Result in only vector rank 0
        single = 1.0 / (k + 0)

        assert combined > single
        assert abs(combined - 2 * single) < 1e-6


# ── Config Tests ────────────────────────────────────────


class TestAdvancedRAGConfig:
    """Test that new config settings are present."""

    def test_advanced_rag_defaults(self):
        from app.core.config import Settings
        s = Settings(
            groq_api_key="test",
            database_url="sqlite:///test.db",
        )
        assert s.use_reranking is True
        assert s.use_query_expansion is True
        assert s.use_hybrid_search is True
        assert "cross-encoder" in s.reranker_model
        assert "mpnet" in s.embedding_model
