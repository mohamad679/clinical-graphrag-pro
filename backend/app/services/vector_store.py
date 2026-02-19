"""
Vector store service using FAISS for local semantic search.
Handles document embedding, indexing, and retrieval.
Supports sentence-aware chunking for high-quality retrieval.
"""

import hashlib
import logging
import pickle
import re
import uuid
from pathlib import Path
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class SearchResult(NamedTuple):
    """A single search result from the vector store."""
    chunk_text: str
    chunk_index: int
    document_id: str
    document_name: str
    score: float


class VectorStoreService:
    """FAISS-based vector store for document chunks."""

    def __init__(self):
        self._index = None
        self._embedder = None
        self._chunks: list[dict] = []  # metadata for each vector
        self._store_path = Path("./data/vector_store")
        self._store_path.mkdir(parents=True, exist_ok=True)

    def _get_embedder(self):
        """Lazy-load sentence transformer model."""
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                from app.core.config import get_settings
                self._embedder = SentenceTransformer(get_settings().embedding_model)
                logger.info(f"Loaded embedding model: {get_settings().embedding_model}")
            except ImportError:
                logger.warning(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
                raise
        return self._embedder

    def _get_index(self):
        """Lazy-load or create FAISS index."""
        if self._index is None:
            try:
                import faiss
                # Try loading existing index
                index_path = self._store_path / "index.faiss"
                meta_path = self._store_path / "chunks.pkl"
                if index_path.exists() and meta_path.exists():
                    self._index = faiss.read_index(str(index_path))
                    with open(meta_path, "rb") as f:
                        self._chunks = pickle.load(f)
                    logger.info(f"Loaded FAISS index with {self._index.ntotal} vectors")
                else:
                    dim = self._get_embedder().get_sentence_embedding_dimension()
                    self._index = faiss.IndexFlatIP(dim)  # inner product (cosine sim with normalized vectors)
                    logger.info(f"Created new FAISS index (dim={dim})")
            except ImportError:
                logger.warning("faiss-cpu not installed. Install with: pip install faiss-cpu")
                raise
        return self._index

    def _save_index(self):
        """Persist index and metadata to disk."""
        import faiss
        faiss.write_index(self._index, str(self._store_path / "index.faiss"))
        with open(self._store_path / "chunks.pkl", "wb") as f:
            pickle.dump(self._chunks, f)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences using regex."""
        # Handle abbreviations like Dr., Mr., etc. before splitting
        text = re.sub(r'\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr|vs|etc|e\.g|i\.e)\.\s', r'\1<DOT> ', text)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        # Restore dots
        sentences = [s.replace('<DOT>', '.') for s in sentences]
        return [s.strip() for s in sentences if s.strip()]

    def chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 64) -> list[dict]:
        """
        Sentence-aware chunking.
        Groups sentences into chunks that respect word-count limits.
        Returns list of dicts: {'chunk_id': str, 'text': str}
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return []

        chunks = []
        current_words: list[str] = []
        current_sentences: list[str] = []

        for sentence in sentences:
            sentence_words = sentence.split()

            # If adding this sentence exceeds the limit, finalize current chunk
            if current_words and len(current_words) + len(sentence_words) > chunk_size:
                chunk_text = " ".join(current_words)
                chunks.append({
                    "chunk_id": str(uuid.uuid4()),
                    "text": chunk_text,
                })

                # Overlap: carry forward the last few sentences
                overlap_words: list[str] = []
                overlap_sents: list[str] = []
                for s in reversed(current_sentences):
                    s_words = s.split()
                    if len(overlap_words) + len(s_words) > overlap:
                        break
                    overlap_words = s_words + overlap_words
                    overlap_sents = [s] + overlap_sents

                current_words = overlap_words
                current_sentences = overlap_sents

            current_words.extend(sentence_words)
            current_sentences.append(sentence)

        # Final chunk
        if current_words:
            chunks.append({
                "chunk_id": str(uuid.uuid4()),
                "text": " ".join(current_words),
            })

        return chunks

    def add_document(
        self,
        document_id: str,
        document_name: str,
        text: str,
        chunk_size: int = 512,
        overlap: int = 64,
    ) -> int:
        """Chunk, embed, and index a document. Returns chunk count."""
        embedder = self._get_embedder()
        index = self._get_index()

        chunk_dicts = self.chunk_text(text, chunk_size, overlap)
        if not chunk_dicts:
            return 0

        chunk_texts = [c["text"] for c in chunk_dicts]

        # Embed all chunks
        embeddings = embedder.encode(chunk_texts, normalize_embeddings=True, show_progress_bar=False)
        embeddings = np.array(embeddings, dtype=np.float32)

        # Add to index
        index.add(embeddings)

        # Store metadata
        for i, cd in enumerate(chunk_dicts):
            self._chunks.append({
                "chunk_id": cd["chunk_id"],
                "chunk_text": cd["text"],
                "chunk_index": i,
                "document_id": document_id,
                "document_name": document_name,
            })

        self._save_index()
        logger.info(f"Indexed {len(chunk_dicts)} chunks for document '{document_name}'")
        return len(chunk_dicts)

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Search for the most relevant chunks given a query."""
        embedder = self._get_embedder()
        index = self._get_index()

        if index.ntotal == 0:
            return []

        query_embedding = embedder.encode(
            [query], normalize_embeddings=True, show_progress_bar=False
        )
        query_embedding = np.array(query_embedding, dtype=np.float32)

        scores, indices = index.search(query_embedding, min(top_k, index.ntotal))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue
            meta = self._chunks[idx]
            results.append(SearchResult(
                chunk_text=meta["chunk_text"],
                chunk_index=meta["chunk_index"],
                document_id=meta["document_id"],
                document_name=meta["document_name"],
                score=float(score),
            ))

        return results

    def get_all_chunks(self) -> list[dict]:
        """Return all stored chunk metadata (used for training data generation)."""
        return list(self._chunks)

    def get_stats(self) -> dict:
        """Return index statistics."""
        try:
            index = self._get_index()
            doc_ids = set(c["document_id"] for c in self._chunks)
            return {
                "total_vectors": index.ntotal,
                "total_chunks": len(self._chunks),
                "total_documents": len(doc_ids),
            }
        except Exception:
            return {"total_vectors": 0, "total_chunks": 0, "total_documents": 0}

    @staticmethod
    def compute_hash(content: bytes) -> str:
        """SHA-256 hash for deduplication."""
        return hashlib.sha256(content).hexdigest()


# Module-level singleton
vector_store_service = VectorStoreService()
