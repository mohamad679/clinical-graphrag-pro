"""
Hybrid Query Engine — orchestrates advanced retrieval pipeline.

Pipeline:
1. Query Expansion — LLM generates alternate phrasings
2. Hybrid Search — FAISS (dense) + BM25 (sparse) merged via RRF
3. Cross-Encoder Reranking — precision re-scoring
4. Citation Extraction — maps claims to source chunks
"""

import logging
from dataclasses import dataclass, field

from app.services.vector_store import vector_store_service, SearchResult
from app.services.bm25_index import bm25_index
from app.services.reranker import reranker_service
from app.services.llm import llm_service
from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class EnrichedResult:
    """Final result from the query engine."""
    query: str
    expanded_queries: list[str]
    results: list[dict]
    retrieval_method: str  # "hybrid", "vector", "bm25"
    reranked: bool
    total_candidates: int


class QueryEngine:
    """
    Advanced hybrid query engine.
    Combines dense (FAISS) and sparse (BM25) retrieval
    with optional query expansion and cross-encoder reranking.
    """

    async def query(
        self,
        query: str,
        top_k: int = 5,
        use_reranking: bool | None = None,
        expand_query: bool | None = None,
        use_hybrid: bool | None = None,
    ) -> EnrichedResult:
        """
        Run the full advanced retrieval pipeline.
        Settings default to config values if not explicitly passed.
        """
        settings = get_settings()
        if use_reranking is None:
            use_reranking = settings.use_reranking
        if expand_query is None:
            expand_query = settings.use_query_expansion
        if use_hybrid is None:
            use_hybrid = settings.use_hybrid_search

        # ── 1. Query Expansion ───────────────────────────
        queries = [query]
        if expand_query:
            try:
                expanded = await self._expand_query(query)
                queries.extend(expanded)
                logger.info(f"Expanded query into {len(queries)} variants")
            except Exception as e:
                logger.warning(f"Query expansion failed: {e}")

        # ── 2. Multi-query Retrieval ─────────────────────
        fetch_k = top_k * 3  # fetch more for reranking

        all_candidates: dict[str, dict] = {}  # keyed by chunk_text to deduplicate

        for q in queries:
            # Dense (vector) search
            vector_results = vector_store_service.search(q, top_k=fetch_k)
            for r in vector_results:
                key = f"{r.document_id}:{r.chunk_index}"
                if key not in all_candidates:
                    all_candidates[key] = {
                        "chunk_text": r.chunk_text,
                        "chunk_index": r.chunk_index,
                        "document_id": r.document_id,
                        "document_name": r.document_name,
                        "score": 0.0,
                        "vector_rank": None,
                        "bm25_rank": None,
                    }

            # Sparse (BM25) search
            if use_hybrid:
                bm25_results = bm25_index.search(q, top_k=fetch_k)
                for r in bm25_results:
                    key = f"{r['document_id']}:{r['chunk_index']}"
                    if key not in all_candidates:
                        all_candidates[key] = {
                            "chunk_text": r["chunk_text"],
                            "chunk_index": r["chunk_index"],
                            "document_id": r["document_id"],
                            "document_name": r["document_name"],
                            "score": 0.0,
                            "vector_rank": None,
                            "bm25_rank": None,
                        }

        total_candidates = len(all_candidates)

        if not all_candidates:
            return EnrichedResult(
                query=query,
                expanded_queries=queries[1:],
                results=[],
                retrieval_method="hybrid" if use_hybrid else "vector",
                reranked=False,
                total_candidates=0,
            )

        # ── 3. Reciprocal Rank Fusion (RRF) ──────────────
        if use_hybrid:
            candidates_list = self._rrf_merge(query, list(all_candidates.values()), fetch_k)
        else:
            # Sort by vector score only
            candidates_list = sorted(
                all_candidates.values(),
                key=lambda x: x["score"],
                reverse=True,
            )[:fetch_k]

        # ── 4. Cross-Encoder Reranking ───────────────────
        if use_reranking and candidates_list:
            try:
                reranked = reranker_service.rerank(query, candidates_list, top_k=top_k)
                final_results = [
                    {
                        "chunk_text": r.chunk_text,
                        "chunk_index": r.chunk_index,
                        "document_id": r.document_id,
                        "document_name": r.document_name,
                        "score": r.rerank_score,
                        "original_score": r.original_score,
                    }
                    for r in reranked
                ]
                logger.info(f"Reranked {len(candidates_list)} → {len(final_results)} results")
            except Exception as e:
                logger.warning(f"Reranking failed, using fusion scores: {e}")
                use_reranking = False
                final_results = candidates_list[:top_k]
        else:
            final_results = candidates_list[:top_k]

        return EnrichedResult(
            query=query,
            expanded_queries=queries[1:],
            results=final_results,
            retrieval_method="hybrid" if use_hybrid else "vector",
            reranked=use_reranking,
            total_candidates=total_candidates,
        )

    def _rrf_merge(
        self,
        query: str,
        candidates: list[dict],
        fetch_k: int,
        k: int = 60,
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion.
        Merges rankings from vector and BM25 search.
        RRF_score = Σ 1 / (k + rank_i) for each ranking system
        """
        # Get fresh rankings for RRF
        vector_results = vector_store_service.search(query, top_k=fetch_k)
        bm25_results = bm25_index.search(query, top_k=fetch_k)

        # Build rank maps
        vector_ranks = {}
        for rank, r in enumerate(vector_results):
            key = f"{r.document_id}:{r.chunk_index}"
            vector_ranks[key] = rank

        bm25_ranks = {}
        for rank, r in enumerate(bm25_results):
            key = f"{r['document_id']}:{r['chunk_index']}"
            bm25_ranks[key] = rank

        # Compute RRF score for each candidate
        for c in candidates:
            key = f"{c['document_id']}:{c['chunk_index']}"
            rrf_score = 0.0

            if key in vector_ranks:
                rrf_score += 1.0 / (k + vector_ranks[key])
            if key in bm25_ranks:
                rrf_score += 1.0 / (k + bm25_ranks[key])

            c["score"] = rrf_score

        # Sort by RRF score
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    async def _expand_query(self, query: str, n: int = 2) -> list[str]:
        """
        Use LLM to generate alternate phrasings of the query.
        Focuses on medical synonyms and terminology variations.
        """
        prompt = (
            f"Generate {n} alternative phrasings of this medical query. "
            f"Use different medical terminology, synonyms, or acronyms. "
            f"Return ONLY the alternative queries, one per line, no numbering.\n\n"
            f"Original: {query}"
        )

        response = await llm_service.generate(
            user_message=prompt,
            context="",
        )

        # Parse response into individual queries
        alternatives = [
            line.strip()
            for line in response.strip().split("\n")
            if line.strip() and len(line.strip()) > 5
        ]

        return alternatives[:n]


# Module-level singleton
query_engine = QueryEngine()
