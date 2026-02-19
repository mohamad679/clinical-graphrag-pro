"""
Cross-encoder reranker service.
Re-scores candidate passages using a cross-encoder model
for higher-precision retrieval after initial recall.
"""

import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


class RankedResult(NamedTuple):
    """A reranked search result."""
    chunk_text: str
    chunk_index: int
    document_id: str
    document_name: str
    original_score: float
    rerank_score: float


class RerankerService:
    """Cross-encoder reranker for second-stage retrieval."""

    def __init__(self):
        self._model = None

    def _get_model(self):
        """Lazy-load cross-encoder model."""
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                from app.core.config import get_settings

                model_name = get_settings().reranker_model
                self._model = CrossEncoder(model_name, max_length=512)
                logger.info(f"Loaded reranker model: {model_name}")
            except ImportError:
                logger.warning(
                    "sentence-transformers not installed. "
                    "Reranking disabled."
                )
                raise
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 5,
    ) -> list[RankedResult]:
        """
        Rerank candidate passages using cross-encoder.

        candidates: list of dicts with keys:
            chunk_text, chunk_index, document_id, document_name, score
        """
        if not candidates:
            return []

        try:
            model = self._get_model()
        except Exception:
            # Graceful fallback: return candidates as-is
            logger.warning("Reranker unavailable, returning original order")
            return [
                RankedResult(
                    chunk_text=c["chunk_text"],
                    chunk_index=c["chunk_index"],
                    document_id=c["document_id"],
                    document_name=c["document_name"],
                    original_score=c.get("score", 0.0),
                    rerank_score=c.get("score", 0.0),
                )
                for c in candidates[:top_k]
            ]

        # Build query-passage pairs
        pairs = [(query, c["chunk_text"]) for c in candidates]

        # Score all pairs
        scores = model.predict(pairs)

        # Combine with metadata and sort
        scored = []
        for i, c in enumerate(candidates):
            scored.append(RankedResult(
                chunk_text=c["chunk_text"],
                chunk_index=c["chunk_index"],
                document_id=c["document_id"],
                document_name=c["document_name"],
                original_score=c.get("score", 0.0),
                rerank_score=float(scores[i]),
            ))

        # Sort by rerank score descending
        scored.sort(key=lambda x: x.rerank_score, reverse=True)
        return scored[:top_k]


# Module-level singleton
reranker_service = RerankerService()
