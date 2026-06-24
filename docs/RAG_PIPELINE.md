# Hardened Clinical RAG Retrieval Pipeline

This document details the architecture, multi-tenant isolation, and safety controls implemented in the retrieval pipeline of Clinical GraphRAG Pro.

---

## 1. Unified Retrieval Gateway

All retrieval pathways (including chat RAG, agent tools, temporal graph search, and `/graph/search` API endpoints) are unified under a single gateway: **`QueryEngine.query`** in [query_engine.py](../backend/app/services/query_engine.py).

This guarantees that all callers enforce the same query expansion, reciprocal rank fusion (RRF), cross-encoder reranking, and access-control validation rules.

### Supported Modes:
- `"dense"`: Vector search only.
- `"sparse"`: Keyword sparse search only. Local evaluation uses `rank_bm25.BM25Okapi`; PostgreSQL runtime uses Full-Text Search.
- `"hybrid"`: Vector + sparse retrieval combined using reciprocal rank fusion (RRF).
- `"hybrid_rerank"`: Vector + sparse retrieval + second-stage Cross-Encoder reranking.

---

## 2. Access Isolation & Fail-Closed Security

The RAG pipeline operates on a strict **fail-closed security model** to prevent cross-tenant, cross-user, or cross-patient data leakage:
- Every query must supply access-isolation context filters: `user_id`, `tenant_id`, `patient_id`, `organization_id`, or `owner`.
- If a retrieval query is made without **any** of these parameters, it immediately raises a `ValueError` ("Access isolation context missing"), refusing to execute the search.
- The default behavior can only be bypassed if `allow_unfiltered=True` is explicitly passed (restricted to administrators or internal test suites).

---

## 3. Adaptive Overfetching (FAISS/Qdrant)

To prevent post-filtering candidate starvation in local vector stores:
- **FAISS Backend**: In [vector_store.py](../backend/app/services/vector_store.py), when metadata filters are applied, the search dynamically sets the initial candidate retrieval parameter `initial_k = index.ntotal`. This guarantees exact post-filtering over all indexed vectors.
- **Qdrant Backend**: Employs Qdrant's native pre-filtering engine using nested match conditions to evaluate only vectors matching the isolation filters.

---

## 4. Multi-Tenant Sparse Search Isolation

In [bm25_index.py](../backend/app/services/bm25_index.py), keyword search enforces access boundary checks:
- **PostgreSQL Mode**: Uses generated `document_chunks.search_vector` Full-Text Search indexes coupled with JSONB metadata querying. Ranking uses `ts_rank_cd`; this database runtime path is not BM25.
  ```sql
  (DocumentChunk.user_id == val) |
  (DocumentChunk.metadata_['tenant_id'].astext == val) |
  (DocumentChunk.metadata_['owner'].astext == val)
  ```
- **In-Memory/SQLite Fallback Mode**: Applies strict Python-level post-filtering immediately after computing `rank_bm25.BM25Okapi` scores, or token-overlap fallback scores when the package is unavailable, to reject unauthorized chunks before returning results.

---

## 5. Reciprocal Rank Fusion & Reranking Safety Bounds

- **RRF Merge**: The fusion algorithm (`_rrf_merge`) merges vector search and sparse results only within the retrieved list that has already been filtered by the isolation bounds.
- **Reranker Isolation**: The second-stage Cross-Encoder rerank (`reranker_service.rerank_with_metadata`) is performed **only** on candidates that have successfully passed the vector/sparse access checks, avoiding any potential leakage of unauthorized data into the cross-encoder context or scoring bias.

---

## 6. Diagnostic Traces and Latency Profiling

When `trace=True` or `settings.debug` is enabled, the query gateway returns an `EnrichedResult` containing a detailed `trace_info` dictionary. This profiles the performance and candidate lifecycle across all execution stages:
- Latencies per pipeline stage (`query_expansion_ms`, `vector_search_ms`, `sparse_search_ms`, `merge_ms`, `rerank_ms`).
- Count metrics showing pre-merge, post-merge, and post-filtering candidate counts.
- Explicit lists of `final_chunk_ids` and `final_document_ids` returned by the retrieval run.

---

## 7. Clinical Grounding, Citation Validation, & Safety Gates

To prevent false confidence and LLM hallucinations in clinical settings, the RAG generation pipeline enforces strict verification policies during answer generation. Demo outputs require clinician review.

### 1. Zero Silent Footers
The RAG pipeline never silently appends a citation footer (e.g. `Supporting citations: [SRC1] [SRC2]`) to answers that do not have inline citation markers. Factual claims must be directly tied to sources inline.

### 2. Validation & One-Time Regeneration Loop
When generating answers:
- The system parses inline citations including source chunks (`[SRC1]`, `[DOC1]`, `[IMG1]`) and fact-level graph citations such as `[GRAPH-COND-001]`.
- It performs validation checks:
  1. **Invented Citations**: Verifies that every citation marker exists in the retrieved context items.
  2. **Security & Scope Violation**: Verifies that every cited item belongs to the active tenant/patient scope.
  3. **Graph Provenance**: Graph citations map to exactly one graph fact with source document and source chunk provenance.
  4. **Structured Grounding**: Deterministic validators check citation existence, tenant/patient match, provenance, numeric values, units, negation, medication status, and temporal state.
- If the first generation pass contains zero valid citations or any invalid/invented citations, the system automatically triggers a one-time regeneration with stricter grounding instructions.
- If the second pass still fails validation, the system abstains and returns the safe clinical fallback:
  *"I do not have enough evidence in the provided documents to answer this safely."*

### 3. Heuristic Evidence-Support Score
The API reports `heuristic_evidence_support_score`.

This value is a heuristic evidence-support score, not calibrated clinical confidence.

The score is computed considering:
- Retrieval and reranker scores of cited chunks.
- Evidence coverage (the ratio of cited chunks to retrieved chunks).
- Invalid citation penalties (score drops to `0.0` if any invented or out-of-scope citation is found).
- Fact-level graph provenance: Graph facts without source document and source chunk provenance are excluded from RAG context and cannot support claims.

The legacy `confidence_score` response field is deprecated and currently mirrors `heuristic_evidence_support_score` only for compatibility.

### 4. Prompt Injection Hardening
Context documents and graph text are treated as untrusted data, not instructions. The RAG system prompt explicitly commands the model to ignore any instructions, system overrides, key requests, or policy changes embedded inside the retrieved records (e.g. "Ignore previous instructions", "Reveal API keys").
