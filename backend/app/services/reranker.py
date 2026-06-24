"""
Cross-encoder reranker service.
Re-scores candidate passages using a cross-encoder model
for higher-precision retrieval after initial recall.
"""

import logging
import time
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
    chunk_id: str = ""
    page_start: int | None = None
    page_end: int | None = None
    source_offset_start: int | None = None
    source_offset_end: int | None = None


class RerankResult(NamedTuple):
    """Reranker output plus explicit execution/fallback metadata."""
    items: list[RankedResult]
    applied: bool
    model_loaded: bool
    fallback_reason: str | None
    latency_ms: float


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
        patient_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[RankedResult]:
        """Compatibility wrapper returning only ranked items."""
        return self.rerank_with_metadata(
            query,
            candidates,
            top_k=top_k,
            patient_id=patient_id,
            tenant_id=tenant_id,
        ).items

    def rerank_with_metadata(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 5,
        patient_id: str | None = None,
        tenant_id: str | None = None,
    ) -> RerankResult:
        """
        Rerank candidate passages using cross-encoder.

        candidates: list of dicts with keys:
            chunk_text, chunk_index, document_id, document_name, score
        """
        if not candidates:
            return RerankResult([], applied=False, model_loaded=False, fallback_reason="no_candidates", latency_ms=0.0)

        from app.core.caching import CacheManager, make_cache_key

        cache_key = None
        started = time.perf_counter()
        try:
            cache_key = make_cache_key(
                namespace="rerank",
                patient_id=patient_id,
                tenant_id=tenant_id,
                payload={"query": query, "candidates": candidates, "top_k": top_k}
            )
            cached_res = CacheManager.get(cache_key)
            if cached_res is not None:
                if isinstance(cached_res, dict) and "items" in cached_res:
                    cached_items = cached_res.get("items") or []
                    metadata = cached_res
                else:
                    cached_items = cached_res
                    metadata = {
                        "applied": True,
                        "model_loaded": True,
                        "fallback_reason": None,
                    }
                items = [
                        RankedResult(
                            chunk_text=r["chunk_text"],
                            chunk_index=r["chunk_index"],
                            document_id=r["document_id"],
                            document_name=r["document_name"],
                            original_score=r["original_score"],
                            rerank_score=r["rerank_score"],
                            chunk_id=r.get("chunk_id", ""),
                            page_start=r.get("page_start"),
                            page_end=r.get("page_end"),
                            source_offset_start=r.get("source_offset_start"),
                            source_offset_end=r.get("source_offset_end"),
                        )
                        for r in cached_items
                    ]
                return RerankResult(
                    items,
                    applied=bool(metadata.get("applied")),
                    model_loaded=bool(metadata.get("model_loaded")),
                    fallback_reason=metadata.get("fallback_reason"),
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
        except ValueError:
            # Bypass cache on missing patient/tenant context parameter
            pass

        from app.core.metrics import observe_reranker
        try:
            try:
                model = self._get_model()
            except Exception as exc:
                fallback_reason = f"model_unavailable:{exc.__class__.__name__}"
                logger.warning("Reranker unavailable, returning original order: %s", fallback_reason)
                fallback_results = [
                    RankedResult(
                        chunk_text=c["chunk_text"],
                        chunk_index=c["chunk_index"],
                        document_id=c["document_id"],
                        document_name=c["document_name"],
                        original_score=c.get("score", 0.0),
                        rerank_score=c.get("score", 0.0),
                        chunk_id=c.get("chunk_id", ""),
                        page_start=c.get("page_start"),
                        page_end=c.get("page_end"),
                        source_offset_start=c.get("source_offset_start"),
                        source_offset_end=c.get("source_offset_end"),
                    )
                    for c in candidates[:top_k]
                ]
                if cache_key is not None:
                    CacheManager.set(cache_key, self._serialize_result(
                        fallback_results,
                        applied=False,
                        model_loaded=False,
                        fallback_reason=fallback_reason,
                    ))
                return RerankResult(
                    fallback_results,
                    applied=False,
                    model_loaded=False,
                    fallback_reason=fallback_reason,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )

            # Build query-passage pairs
            pairs = [(query, c["chunk_text"]) for c in candidates]

            # Score all pairs
            try:
                scores = model.predict(pairs)
            except Exception as exc:
                fallback_reason = f"prediction_failed:{exc.__class__.__name__}"
                logger.warning("Reranker prediction failed, returning original order: %s", fallback_reason)
                fallback_results = [
                    RankedResult(
                        chunk_text=c["chunk_text"],
                        chunk_index=c["chunk_index"],
                        document_id=c["document_id"],
                        document_name=c["document_name"],
                        original_score=c.get("score", 0.0),
                        rerank_score=c.get("score", 0.0),
                        chunk_id=c.get("chunk_id", ""),
                        page_start=c.get("page_start"),
                        page_end=c.get("page_end"),
                        source_offset_start=c.get("source_offset_start"),
                        source_offset_end=c.get("source_offset_end"),
                    )
                    for c in candidates[:top_k]
                ]
                return RerankResult(
                    fallback_results,
                    applied=False,
                    model_loaded=True,
                    fallback_reason=fallback_reason,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )

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
                    chunk_id=c.get("chunk_id", ""),
                    page_start=c.get("page_start"),
                    page_end=c.get("page_end"),
                    source_offset_start=c.get("source_offset_start"),
                    source_offset_end=c.get("source_offset_end"),
                ))

            # Sort by rerank score descending
            scored.sort(key=lambda x: x.rerank_score, reverse=True)
            final_subset = scored[:top_k]
            if cache_key is not None:
                CacheManager.set(cache_key, self._serialize_result(
                    final_subset,
                    applied=True,
                    model_loaded=True,
                    fallback_reason=None,
                ))
            return RerankResult(
                final_subset,
                applied=True,
                model_loaded=True,
                fallback_reason=None,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        finally:
            observe_reranker((time.perf_counter() - started) * 1000)

    @staticmethod
    def _serialize_result(
        items: list[RankedResult],
        *,
        applied: bool,
        model_loaded: bool,
        fallback_reason: str | None,
    ) -> dict:
        return {
            "items": [
                {
                    "chunk_text": r.chunk_text,
                    "chunk_index": r.chunk_index,
                    "document_id": r.document_id,
                    "document_name": r.document_name,
                    "original_score": r.original_score,
                    "rerank_score": r.rerank_score,
                    "chunk_id": r.chunk_id,
                    "page_start": r.page_start,
                    "page_end": r.page_end,
                    "source_offset_start": r.source_offset_start,
                    "source_offset_end": r.source_offset_end,
                }
                for r in items
            ],
            "applied": applied,
            "model_loaded": model_loaded,
            "fallback_reason": fallback_reason,
        }



# Module-level singleton
reranker_service = RerankerService()
