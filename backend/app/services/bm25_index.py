"""
BM25 keyword search index.
Provides sparse retrieval to complement FAISS dense retrieval
for hybrid search via Reciprocal Rank Fusion (RRF).
"""

import logging
import pickle
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class BM25Index:
    """BM25 keyword index for sparse retrieval."""

    def __init__(self):
        self._index = None
        self._corpus: list[list[str]] = []  # tokenized docs
        self._metadata: list[dict] = []     # chunk metadata
        self._store_path = Path("./data/bm25_store")
        self._store_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple medical-aware tokenizer."""
        text = text.lower()
        # Keep hyphens in medical terms (e.g., "beta-blocker")
        tokens = re.findall(r'\b[\w-]+\b', text)
        # Remove very short tokens (except known abbreviations)
        return [t for t in tokens if len(t) > 1]

    def _load_index(self):
        """Load persisted BM25 index from disk."""
        corpus_path = self._store_path / "bm25_corpus.pkl"
        meta_path = self._store_path / "bm25_meta.pkl"

        if corpus_path.exists() and meta_path.exists():
            with open(corpus_path, "rb") as f:
                self._corpus = pickle.load(f)
            with open(meta_path, "rb") as f:
                self._metadata = pickle.load(f)
            self._rebuild_index()
            logger.info(f"Loaded BM25 index with {len(self._corpus)} documents")

    def _save_index(self):
        """Persist corpus and metadata to disk."""
        with open(self._store_path / "bm25_corpus.pkl", "wb") as f:
            pickle.dump(self._corpus, f)
        with open(self._store_path / "bm25_meta.pkl", "wb") as f:
            pickle.dump(self._metadata, f)

    def _rebuild_index(self):
        """Rebuild BM25 index from corpus."""
        if not self._corpus:
            self._index = None
            return

        try:
            from rank_bm25 import BM25Okapi
            self._index = BM25Okapi(self._corpus)
        except ImportError:
            logger.warning("rank-bm25 not installed. Install with: pip install rank-bm25")
            self._index = None

    def add_document(
        self,
        chunks: list[dict],
        document_id: str,
        document_name: str,
    ) -> int:
        """
        Add document chunks to the BM25 index.
        chunks: list of {'chunk_id': str, 'text': str, 'chunk_index': int}
        """
        if not self._corpus and not self._index:
            self._load_index()

        for chunk in chunks:
            tokens = self._tokenize(chunk["text"])
            self._corpus.append(tokens)
            self._metadata.append({
                "chunk_id": chunk.get("chunk_id", ""),
                "chunk_text": chunk["text"],
                "chunk_index": chunk.get("chunk_index", 0),
                "document_id": document_id,
                "document_name": document_name,
            })

        self._rebuild_index()
        self._save_index()
        logger.info(f"BM25: indexed {len(chunks)} chunks for '{document_name}'")
        return len(chunks)

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """
        Search the BM25 index.
        Returns list of dicts with keys: chunk_text, chunk_index, document_id, document_name, score
        """
        if not self._index:
            self._load_index()

        if not self._index or not self._corpus:
            return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        scores = self._index.get_scores(tokens)

        # Get top-k indices
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            meta = self._metadata[idx]
            results.append({
                "chunk_text": meta["chunk_text"],
                "chunk_index": meta["chunk_index"],
                "document_id": meta["document_id"],
                "document_name": meta["document_name"],
                "score": float(scores[idx]),
            })

        return results

    def get_stats(self) -> dict:
        """Return BM25 index statistics."""
        return {
            "total_documents": len(self._corpus),
            "index_loaded": self._index is not None,
        }


# Module-level singleton
bm25_index = BM25Index()
