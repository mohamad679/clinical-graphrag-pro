# ADR-001: Hybrid Retrieval

## Status
Accepted

## Context

Clinical questions often mix semantic phrasing with exact lexical anchors such as medication names, abbreviations, lab names, and dosages. Dense retrieval alone is good at paraphrase matching, but it can miss clinically important tokens that sparse retrieval preserves.

## Decision

We use a hybrid retrieval pipeline built from FAISS dense search, BM25 sparse search, and reciprocal rank fusion in `backend/app/services/query_engine.py`. We optionally apply a cross-encoder reranker after fusion to improve final passage ordering.

## Alternatives Considered

- **Dense-only retrieval**: rejected because exact medical terms and abbreviations benefit from a lexical path.
- **Sparse-only retrieval**: rejected because it performs poorly on paraphrases and narrative variation.

## Consequences

**Positive:**
- Better recall on exact terms such as drugs, labs, and abbreviations.
- More robust ranking when questions mix keywords and narrative phrasing.
- Fusion remains simple because RRF does not depend on score normalization.

**Negative:**
- Retrieval is more complex to reason about than a single backend.
- Indexing and maintenance now span both vector and sparse stores.
- Optional reranking adds model load and latency.

## Date
2026-03-24
