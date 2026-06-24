# Benchmarks & Verification

These benchmarks are small internal measurements for regression tracking and pipeline sanity checks. They are **not clinical validation** and do not prove the system is safe for diagnosis, treatment, triage, medication decisions, or patient care.

---

## Reproducible Evaluation Scripts

We have implemented two verification scripts to run evaluations and verify RAG performance out-of-the-box from a fresh clone:

### 1. Retrieval Benchmark (`scripts/evaluate_retrieval.py`)
Assesses dense, sparse, and hybrid retrieval quality on the golden dataset. Calculates Recall@k, Precision@k, MRR, nDCG, and latency profiles without calling external LLM providers.
To run:
```bash
python scripts/evaluate_retrieval.py
```

### 2. RAG Quality & Safety Benchmark (`scripts/evaluate_rag.py`)
Evaluates out-of-context abstention accuracy, citation coverage, citation accuracy, and end-to-end response latency.
To run:
```bash
python scripts/evaluate_rag.py
```
*Note: Grounded Q&A evaluations require configuring an LLM API key in `backend/.env`. If missing, LLM-dependent tests are skipped safely while abstention and latency checks run offline.*

---

## Retrieval Performance

### Smoke Test — Golden Dataset (n=5, single relevant doc per query)
| Mode    | Recall@5 | Precision@5 | MRR    | nDCG@5 |
|---------|----------|-------------|--------|--------|
| FAISS   | 1.0000   | 0.2000      | 1.0000 | 1.0000 |
| BM25    | 1.0000   | 0.2000      | 1.0000 | 1.0000 |
| Hybrid  | 1.0000   | 0.2000      | 1.0000 | 1.0000 |

Note: In a 5-chunk corpus with top_k=5, every method trivially achieves Recall@5=1.0. These numbers verify the pipeline works, not that retrieval is robust.

### Keyword Hit Test — Retrieval Pairs (n=20)
| Mode   | Keyword Hit Rate |
|--------|-----------------|
| FAISS  | 100%            |
| BM25   | 100%            |
| Hybrid | 100%            |

Note: BM25 Recall@1=0.0 in results/retrieval_evaluation_results.json refers to a separate run on the 5-case golden dataset with exact-match scoring. This is expected: BM25 token-overlap may miss semantic matches in a corpus this small. Both results are preserved for transparency.

> ⚠️ All retrieval benchmarks must be run with OFFLINE_DEMO_MODE=false and a real embedding model. Results generated with EMBEDDING_MODEL=deterministic-local are not semantically meaningful.

---

## External Benchmarks & MedQA
*   **Status**: External evaluations (such as MedQA-100) are not run by default during local builds. They are marked as **Not Evaluated** unless live LLM provider credentials (`GROQ_API_KEY` or `GOOGLE_API_KEY`) are set in the environment and `python backend/scripts/run_benchmark.py` is explicitly invoked.
*   Do not trust or display any benchmark score unless it has been generated dynamically by your local environment.

---

## Baseline Latency Profile

Measured using the `scripts/evaluate_retrieval.py` script (average times):

| Operation | Average Latency (ms) | Notes |
| --- | ---: | --- |
| Embedding generation | ~12.5 ms | Query embedding encoding |
| FAISS vector search | ~0.08 ms | Flat IP search over indexed chunks |
| BM25 search | ~0.15 ms | In-memory token overlap search |
| RRF fusion | ~0.01 ms | Merging dense and sparse results |

---

## System Configuration

| Component | Value |
| --- | --- |
| Vector Index | FAISS `IndexFlatIP` |
| Embedding Model | `sentence-transformers/all-mpnet-base-v2` (768-dim) |
| Sparse Retrieval | BM25 (`rank-bm25` in-memory fallback / pg_trgm in DB) |
| Fusion | Reciprocal Rank Fusion (`k=60`) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| LLM | `gemini-2.0-flash` (default) / `llama-3.3-70b-versatile` (optional) |
| Chunk Size | `512` words |
| Chunk Overlap | `64` words |
