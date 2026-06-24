# ADR-001: Hybrid Retrieval Over Dense-Only Retrieval

**Date:** 2026-04-01  
**Status:** Accepted  
**Deciders:** Solo developer  

## Context
Clinical search in this repository has to retrieve both semantic paraphrases and literal tokens such as medication names, dosages, acronyms, and lab values. The current dense path is implemented in `backend/app/services/vector_store.py` through `FAISSBackend.search()`. The sparse path is implemented in `backend/app/services/bm25_index.py` through `BM25Index.search()` and `BM25Index.search_async()`. The orchestration point in `backend/app/services/query_engine.py` already executes both paths inside `QueryEngine.query()`.

Dense retrieval alone is a poor fit for some clinical identifiers. The embedding stack in this project comes from `sentence-transformers==3.3.1` in `backend/requirements.txt`, which is effective for semantic similarity but does not guarantee exact lexical recall for strings such as `STEMI`, `HbA1c`, or dosage text. Sparse retrieval alone has the opposite failure mode: it preserves literals well but does not generalize to paraphrase or terminology variation.

## Decision
Use hybrid retrieval as the default retrieval strategy. `QueryEngine.query()` runs FAISS dense search and BM25 sparse search, deduplicates candidates, and combines the rankings with Reciprocal Rank Fusion in `QueryEngine._rrf_merge(k=60)`. This is controlled by `settings.use_hybrid_search` in `backend/app/core/config.py`.

The accepted design is therefore:
- Dense retrieval for semantic recall through `vector_store_service.search(...)`.
- Sparse retrieval for literal token matching through `bm25_index.search(...)`.
- Rank merging through RRF instead of a weighted sum.

## Consequences
**Positive:** Exact-match clinical strings are recoverable through BM25, while semantically related phrasing is still recoverable through FAISS. Because `QueryEngine._rrf_merge()` operates on rank positions instead of raw scores, the implementation avoids score calibration between cosine-style dense scores and BM25 scores.  
**Negative:** The ingestion and retrieval paths now maintain two retrieval stores instead of one: FAISS chunk metadata in `backend/app/services/vector_store.py` and sparse retrieval data in `backend/app/models/persistence.py` / `backend/app/services/bm25_index.py`. `QueryEngine.query()` also performs more retrieval work per request than a dense-only path.  
**Risks:** The two stores can drift if document chunking, deletion, or metadata updates are not applied consistently to both backends. Optional query expansion in `QueryEngine._expand_query()` introduces another model-generated step, so hybrid retrieval does not remove the need to keep `use_query_expansion` configurable.

## Alternatives Considered
| Alternative | Why Rejected |
|-------------|--------------|
| Dense-only retrieval with optional query expansion | `QueryEngine._expand_query()` is LLM-generated and adds another failure mode, but still does not guarantee literal recall for clinical identifiers and dosage strings. |
| Weighted linear combination of dense and sparse scores | `QueryEngine.query()` receives dense and BM25 scores on different scales. A weighted sum would require calibration logic that does not exist in the current codebase. |
| Sparse-only retrieval | BM25 preserves exact tokens, but it does not cover the semantic paraphrase use case that the FAISS path already supports. |
| Late-interaction rerank-first architecture | The current repository is built around FAISS, BM25, and an optional second-stage reranker. A late-interaction design would require a different indexing and serving stack than the one implemented today. |
