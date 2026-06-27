"""
Hybrid Query Engine — orchestrates advanced retrieval pipeline.

Pipeline:
1. Query Expansion — LLM generates alternate phrasings
2. Hybrid Search — FAISS (dense) + BM25 (sparse) merged via RRF
3. Cross-Encoder Reranking — precision re-scoring
4. Citation Extraction — maps claims to source chunks
"""

import logging
import inspect
from dataclasses import dataclass
from time import perf_counter

from app.services.vector_store import vector_store_service
from app.services.bm25_index import bm25_index
from app.services.reranker import reranker_service
from app.services.llm import llm_service
from app.core.config import get_settings
from app.core.metrics import observe_rag_retrieval
from app.core.retrieval_scope import RetrievalScope

logger = logging.getLogger(__name__)


def _candidate_snapshot(results: list[dict], *, score_key: str = "score") -> list[dict]:
    """Return safe candidate diagnostics without passage text."""
    snapshot = []
    for rank, result in enumerate(results):
        snapshot.append(
            {
                "rank": rank,
                "chunk_id": result.get("chunk_id", ""),
                "document_id": result.get("document_id", ""),
                "document_name": result.get("document_name", ""),
                "score": float(result.get(score_key, result.get("score", 0.0)) or 0.0),
            }
        )
    return snapshot


@dataclass
class EnrichedResult:
    """Final result from the query engine."""
    query: str
    expanded_queries: list[str]
    results: list[dict]
    retrieval_method: str  # "hybrid", "vector", "bm25"
    reranked: bool
    total_candidates: int
    retrieval_latency_ms: float
    trace_info: dict | None = None


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
        scope: RetrievalScope | None = None,
        user_id: str | None = None,
        tenant_id: str | None = None,
        patient_id: str | None = None,
        organization_id: str | None = None,
        owner: str | None = None,
        mode: str | None = None,
        filters: dict | None = None,
        allow_unfiltered: bool = False,
        include_scores: bool = True,
        include_metadata: bool = True,
        trace: bool = False,
    ) -> EnrichedResult:
        """
        Run the full advanced retrieval pipeline with strict multi-tenancy enforcement.
        Settings default to config values if not explicitly passed.
        """
        started = perf_counter()
        
        # Build and merge access-control filters. RetrievalScope fields are
        # exact field filters; legacy kwargs are kept only for internal/test
        # compatibility and are not treated as interchangeable aliases.
        merged_filters = dict(filters) if filters else {}
        if scope is not None:
            merged_filters.update(scope.to_filters())
        for key, val in [
            ("user_id", user_id),
            ("tenant_id", tenant_id),
            ("patient_id", patient_id),
            ("organization_id", organization_id),
            ("owner", owner),
        ]:
            if val is not None:
                merged_filters[key] = val

        # Fail-closed validation check
        isolation_keys = {"user_id", "tenant_id", "patient_id", "organization_id", "owner"}
        has_isolation = any(merged_filters.get(k) is not None for k in isolation_keys)
        if not allow_unfiltered and not has_isolation:
            raise ValueError(
                "Access isolation context missing: Query must specify at least one of "
                "user_id, tenant_id, patient_id, organization_id, or owner."
            )

        settings = get_settings()

        # Determine retrieval settings based on mode
        dense_enabled = True
        sparse_enabled = False
        rerank_enabled = False
        
        if mode is not None:
            if mode == "dense":
                dense_enabled = True
                sparse_enabled = False
                rerank_enabled = False
            elif mode == "sparse":
                dense_enabled = False
                sparse_enabled = True
                rerank_enabled = False
            elif mode == "hybrid":
                dense_enabled = True
                sparse_enabled = True
                rerank_enabled = False
            elif mode == "hybrid_rerank":
                dense_enabled = True
                sparse_enabled = True
                rerank_enabled = True
        else:
            if use_hybrid is None:
                use_hybrid = settings.use_hybrid_search
            dense_enabled = True
            sparse_enabled = use_hybrid
            if use_reranking is None:
                use_reranking = settings.use_reranking
            rerank_enabled = use_reranking

        if expand_query is None:
            expand_query = settings.use_query_expansion and settings.llm_provider.lower() != "retrieval-only"

        latency_stages = {}

        # ── 1. Query Expansion ───────────────────────────
        t_start_expand = perf_counter()
        queries = [query]
        if expand_query:
            try:
                expanded = await self._expand_query(query)
                queries.extend(expanded)
                logger.info(f"Expanded query into {len(queries)} variants")
            except Exception as e:
                logger.warning(f"Query expansion failed: {e}")
        latency_stages["query_expansion_ms"] = (perf_counter() - t_start_expand) * 1000

        # ── 2. Multi-query Retrieval ─────────────────────
        fetch_k = top_k * 3  # fetch more for reranking
        all_candidates: dict[str, dict] = {}  # keyed by chunk_text to deduplicate
        
        num_dense = 0
        num_sparse = 0
        dense_rankings: list[dict] = []
        sparse_rankings: list[dict] = []

        # Dense (vector) search
        t_start_dense = perf_counter()
        if dense_enabled:
            for q in queries:
                try:
                    vector_results = vector_store_service.search(q, top_k=fetch_k, filters=merged_filters)
                    num_dense += len(vector_results)
                    dense_rankings.append(
                        {
                            "query_index": len(dense_rankings),
                            "candidate_count": len(vector_results),
                            "candidates": [
                                {
                                    "rank": rank,
                                    "chunk_id": r.chunk_id,
                                    "document_id": r.document_id,
                                    "document_name": r.document_name,
                                    "score": float(r.score),
                                }
                                for rank, r in enumerate(vector_results)
                            ],
                        }
                    )
                    for rank, r in enumerate(vector_results):
                        key = r.chunk_id or f"{r.document_id}:{r.chunk_index}"
                        if key not in all_candidates:
                            all_candidates[key] = {
                                "chunk_text": r.chunk_text,
                                "chunk_index": r.chunk_index,
                                "document_id": r.document_id,
                                "document_name": r.document_name,
                                "chunk_id": r.chunk_id,
                                "page_start": r.page_start,
                                "page_end": r.page_end,
                                "source_offset_start": r.source_offset_start,
                                "source_offset_end": r.source_offset_end,
                                "score": 0.0,
                                "vector_score": 0.0,
                                "bm25_score": 0.0,
                                "vector_ranks": [],
                                "bm25_ranks": [],
                            }
                        candidate = all_candidates[key]
                        candidate["vector_score"] = max(candidate.get("vector_score", 0.0), float(r.score))
                        if "vector_ranks" not in candidate:
                            candidate["vector_ranks"] = []
                        candidate["vector_ranks"].append(rank)
                except Exception as e:
                    logger.warning(f"Dense vector search failed: {e}")
        latency_stages["vector_search_ms"] = (perf_counter() - t_start_dense) * 1000

        # Sparse (BM25) search
        t_start_sparse = perf_counter()
        bm25_stats = None
        sparse_branch_warning = None
        if sparse_enabled:
            try:
                stats_reader = getattr(bm25_index, "get_stats_async", None) or bm25_index.get_stats
                bm25_stats = stats_reader()
                if inspect.isawaitable(bm25_stats):
                    bm25_stats = await bm25_stats
            except Exception as e:
                bm25_stats = {"error": str(e)}
                logger.warning("Unable to read BM25 index diagnostics: %s", e)

            if (
                isinstance(bm25_stats, dict)
                and "total_documents" in bm25_stats
                and int(bm25_stats.get("total_documents") or 0) == 0
            ):
                sparse_branch_warning = "BM25 sparse index is empty while sparse retrieval is enabled."
                if mode in {"sparse", "hybrid", "hybrid_rerank"}:
                    raise RuntimeError(sparse_branch_warning)
                logger.info("%s Returning dense-only or empty retrieval results.", sparse_branch_warning)
                sparse_enabled = False

            for q in queries if sparse_enabled else []:
                try:
                    bm25_results = bm25_index.search(q, top_k=fetch_k, filters=merged_filters)
                    if inspect.isawaitable(bm25_results):
                        bm25_results = await bm25_results
                    num_sparse += len(bm25_results)
                    sparse_rankings.append(
                        {
                            "query_index": len(sparse_rankings),
                            "candidate_count": len(bm25_results),
                            "candidates": [
                                {
                                    "rank": rank,
                                    "chunk_id": r.get("chunk_id", ""),
                                    "document_id": r.get("document_id", ""),
                                    "document_name": r.get("document_name", ""),
                                    "score": float(r.get("score", 0.0) or 0.0),
                                }
                                for rank, r in enumerate(bm25_results)
                            ],
                        }
                    )
                    for rank, r in enumerate(bm25_results):
                        key = r.get("chunk_id") or f"{r['document_id']}:{r['chunk_index']}"
                        if key not in all_candidates:
                            all_candidates[key] = {
                                "chunk_text": r["chunk_text"],
                                "chunk_index": r["chunk_index"],
                                "document_id": r["document_id"],
                                "document_name": r["document_name"],
                                "chunk_id": r.get("chunk_id", ""),
                                "page_start": r.get("page_start"),
                                "page_end": r.get("page_end"),
                                "source_offset_start": r.get("source_offset_start"),
                                "source_offset_end": r.get("source_offset_end"),
                                "score": 0.0,
                                "vector_score": 0.0,
                                "bm25_score": 0.0,
                                "vector_ranks": [],
                                "bm25_ranks": [],
                            }
                        candidate = all_candidates[key]
                        candidate["bm25_score"] = max(candidate.get("bm25_score", 0.0), float(r.get("score", 0.0)))
                        if "bm25_ranks" not in candidate:
                            candidate["bm25_ranks"] = []
                        candidate["bm25_ranks"].append(rank)
                except Exception as e:
                    logger.warning(f"Sparse BM25 search failed: {e}")
            if num_sparse == 0 and isinstance(bm25_stats, dict) and int(bm25_stats.get("total_documents") or 0) > 0:
                sparse_branch_warning = "BM25 index has documents but returned zero scoped candidates."
                logger.warning("%s filters=%s", sparse_branch_warning, merged_filters)
        latency_stages["sparse_search_ms"] = (perf_counter() - t_start_sparse) * 1000

        total_candidates = len(all_candidates)
        
        t_start_merge = perf_counter()
        if not all_candidates:
            latency_stages["merge_ms"] = (perf_counter() - t_start_merge) * 1000
            latency_stages["rerank_ms"] = 0.0
            
            trace_dict = {
                "query": query,
                "retrieval_mode": mode or ("hybrid" if sparse_enabled and dense_enabled else ("sparse" if sparse_enabled else "dense")),
                "filters_applied": merged_filters,
                "num_dense_results": num_dense,
                "num_sparse_results": num_sparse,
                "num_after_merge": 0,
                "num_after_filtering": 0,
                "bm25_index_stats": bm25_stats,
                "sparse_branch_warning": sparse_branch_warning,
                "rrf_input_lists": {
                    "dense_present": dense_enabled,
                    "sparse_present": sparse_enabled,
                    "dense_candidate_count": num_dense,
                    "sparse_candidate_count": num_sparse,
                    "dense_rankings": dense_rankings,
                    "sparse_rankings": sparse_rankings,
                },
                "reranker_applied": False,
                "reranker_model_loaded": False,
                "reranker_fallback_reason": "no_candidates",
                "latency_stages_ms": latency_stages,
                "final_chunk_ids": [],
                "final_document_ids": [],
            }
            
            return EnrichedResult(
                query=query,
                expanded_queries=queries[1:],
                results=[],
                retrieval_method="hybrid" if sparse_enabled and dense_enabled else ("bm25" if sparse_enabled else "vector"),
                reranked=False,
                total_candidates=0,
                retrieval_latency_ms=(perf_counter() - started) * 1000,
                trace_info=trace_dict if (trace or settings.debug) else None,
            )

        # ── 3. Reciprocal Rank Fusion (RRF) ──────────────
        if sparse_enabled and dense_enabled:
            candidates_list = self._rrf_merge(list(all_candidates.values()))
            ret_method = "hybrid"
        elif sparse_enabled:
            candidates_list = sorted(
                all_candidates.values(),
                key=lambda x: x.get("bm25_score", 0.0),
                reverse=True,
            )[:fetch_k]
            for c in candidates_list:
                c["score"] = c.get("bm25_score", 0.0)
            ret_method = "bm25"
        else:
            candidates_list = sorted(
                all_candidates.values(),
                key=lambda x: x.get("vector_score", 0.0),
                reverse=True,
            )[:fetch_k]
            for c in candidates_list:
                c["score"] = c.get("vector_score", 0.0)
            ret_method = "vector"
        latency_stages["merge_ms"] = (perf_counter() - t_start_merge) * 1000
        fusion_output_ranking = _candidate_snapshot(candidates_list)

        # ── 4. Cross-Encoder Reranking ───────────────────
        t_start_rerank = perf_counter()
        reranked_ran = False
        reranker_model_loaded = False
        reranker_fallback_reason = None
        reranker_input_ranking = _candidate_snapshot(candidates_list)
        reranker_output_ranking: list[dict] = []
        if rerank_enabled and candidates_list:
            try:
                patient_id = merged_filters.get("patient_id")
                tenant_id = merged_filters.get("tenant_id")
                rerank_result = reranker_service.rerank_with_metadata(
                    query,
                    candidates_list,
                    top_k=top_k,
                    patient_id=patient_id,
                    tenant_id=tenant_id,
                )
                final_results = [
                    {
                        "chunk_text": r.chunk_text,
                        "chunk_index": r.chunk_index,
                        "document_id": r.document_id,
                        "document_name": r.document_name,
                        "chunk_id": r.chunk_id,
                        "page_start": r.page_start,
                        "page_end": r.page_end,
                        "source_offset_start": r.source_offset_start,
                        "source_offset_end": r.source_offset_end,
                        "score": r.rerank_score,
                        "original_score": r.original_score,
                        "reranker_score": r.rerank_score,
                        "vector_score": next((c["vector_score"] for c in candidates_list if c["chunk_id"] == r.chunk_id), 0.0),
                        "bm25_score": next((c["bm25_score"] for c in candidates_list if c["chunk_id"] == r.chunk_id), 0.0),
                    }
                    for r in rerank_result.items
                ]
                reranked_ran = rerank_result.applied
                reranker_model_loaded = rerank_result.model_loaded
                reranker_fallback_reason = rerank_result.fallback_reason
                reranker_output_ranking = _candidate_snapshot(final_results, score_key="reranker_score")
                logger.info(f"Reranked {len(candidates_list)} → {len(final_results)} results")
            except Exception as e:
                logger.warning(f"Reranking failed, using fusion scores: {e}")
                final_results = candidates_list[:top_k]
                reranker_fallback_reason = f"exception:{e.__class__.__name__}"
        else:
            final_results = candidates_list[:top_k]
        latency_stages["rerank_ms"] = (perf_counter() - t_start_rerank) * 1000

        if not include_scores:
            for r in final_results:
                r.pop("score", None)
                r.pop("original_score", None)
                r.pop("reranker_score", None)
                r.pop("vector_score", None)
                r.pop("bm25_score", None)
                
        if not include_metadata:
            for r in final_results:
                r.pop("page_start", None)
                r.pop("page_end", None)
                r.pop("source_offset_start", None)
                r.pop("source_offset_end", None)

        latency_total = (perf_counter() - started) * 1000
        
        trace_dict = {
            "query": query,
            "retrieval_mode": mode or ("hybrid_rerank" if rerank_enabled else ("hybrid" if sparse_enabled else "dense")),
            "filters_applied": merged_filters,
            "num_dense_results": num_dense,
            "num_sparse_results": num_sparse,
            "num_after_merge": len(candidates_list),
            "num_after_filtering": len(candidates_list),
            "bm25_index_stats": bm25_stats,
            "sparse_branch_warning": sparse_branch_warning,
            "rrf_input_lists": {
                "dense_present": dense_enabled,
                "sparse_present": sparse_enabled,
                "dense_candidate_count": num_dense,
                "sparse_candidate_count": num_sparse,
                "dense_rankings": dense_rankings,
                "sparse_rankings": sparse_rankings,
            },
            "fusion_output_ranking": fusion_output_ranking,
            "reranker_applied": reranked_ran,
            "reranker_model_loaded": reranker_model_loaded,
            "reranker_fallback_reason": reranker_fallback_reason,
            "reranker_input_ranking": reranker_input_ranking,
            "reranker_output_ranking": reranker_output_ranking,
            "latency_stages_ms": latency_stages,
            "final_chunk_ids": [r.get("chunk_id") for r in final_results],
            "final_document_ids": [r.get("document_id") for r in final_results],
        }

        result = EnrichedResult(
            query=query,
            expanded_queries=queries[1:],
            results=final_results,
            retrieval_method=ret_method,
            reranked=reranked_ran,
            total_candidates=total_candidates,
            retrieval_latency_ms=latency_total,
            trace_info=trace_dict if (trace or settings.debug) else None,
        )
        observe_rag_retrieval(result.retrieval_latency_ms / 1000)
        return result

    async def maintenance_unfiltered_query(
        self,
        query: str,
        *,
        top_k: int = 5,
        admin_scope: RetrievalScope,
        **kwargs,
    ) -> EnrichedResult:
        """Explicit internal/admin-only unfiltered retrieval path."""
        if not admin_scope.is_admin:
            raise PermissionError("Unfiltered maintenance retrieval requires an admin RetrievalScope.")
        return await self.query(
            query,
            top_k=top_k,
            allow_unfiltered=True,
            **kwargs,
        )

    def _rrf_merge(self, candidates: list[dict], k: int = 60) -> list[dict]:
        """
        Reciprocal Rank Fusion.
        Merges rankings from vector and BM25 search using average rank across query variants.
        RRF_score = Σ 1 / (k + average_rank_i) for each ranking system
        """
        for c in candidates:
            rrf_score = 0.0

            v_ranks = c.get("vector_ranks", [])
            if v_ranks:
                avg_v_rank = sum(v_ranks) / len(v_ranks)
                rrf_score += 1.0 / (k + avg_v_rank)

            b_ranks = c.get("bm25_ranks", [])
            if b_ranks:
                avg_b_rank = sum(b_ranks) / len(b_ranks)
                rrf_score += 1.0 / (k + avg_b_rank)

            c["score"] = rrf_score

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    async def _expand_query(self, query: str, n: int = 2) -> list[str]:
        """
        Use LLM to generate alternate phrasings of the query.
        Focuses on medical synonyms and terminology variations.
        """
        if get_settings().llm_provider.lower() == "retrieval-only":
            return []
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
