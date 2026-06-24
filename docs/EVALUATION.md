# Evaluation Framework & Methodology

This document outlines the evaluation framework, metrics, and replication steps for Clinical GraphRAG Pro. The evaluation is designed to be mathematically honest and technically useful for regression testing, query pipeline optimization, and safety auditing.

> [!WARNING]
> The evaluation datasets and metrics in this repository are for demonstration and verification purposes only. They do not constitute clinical validation, and the system is not validated for diagnostic accuracy or direct patient care.

## Evaluation Metrics

We calculate two separate tiers of metrics: **Retrieval Metrics** and **Grounded Generation Metrics**. Retrieval evaluation asks whether the system found the right evidence. Generation evaluation asks whether the final answer used that evidence safely.

### 1. Retrieval Metrics
Retrieval metrics assess the quality of the candidate chunks returned by the dense (FAISS), sparse, and hybrid retrieval engines before LLM generation. Local retrieval benchmarks use `rank_bm25.BM25Okapi` for sparse retrieval when available. Database runtime sparse retrieval uses PostgreSQL Full-Text Search with `ts_rank_cd`; it should not be described as BM25. `deterministic-local` embeddings are used for deterministic offline tests and are not semantic production embeddings. Semantic retrieval benchmarks should report the actual embedding backend and model used.
*   **Recall@k** (k=1, 3, 5): The fraction of expected context documents successfully retrieved within the top $k$ results.
*   **Precision@k** (k=1, 3, 5): The fraction of retrieved documents within the top $k$ that are relevant.
*   **MRR (Mean Reciprocal Rank)**: Evaluates the rank of the first relevant chunk. $MRR = \frac{1}{\text{rank}_1}$ (or $0.0$ if no relevant chunk is in the top $k$).
*   **nDCG@k (Normalized Discounted Cumulative Gain)**: Evaluates ranking quality by penalizing relevant items positioned lower in the list using logarithmic discounting.
*   **Latency Profile**: Tracks retrieval time in milliseconds (mean, p50, p95, and p99).
*   **Failure Counters**: Tracks zero-result rate, empty sparse-index failures, and authorization-filter rejection counts.

### 2. Grounded Generation Metrics
Generation metrics evaluate the correctness, safety behavior, and grounding of the final synthesized answer after evidence has been retrieved.
*   **Citation Precision**: The fraction of cited chunks that are required evidence chunks for the case.
*   **Citation Recall**: The fraction of required evidence chunks cited in the generated answer.
*   **Unsupported Claim Rate**: A deterministic proxy for claims that are not supported by required evidence, contain forbidden assertions, or cite unknown chunks.
*   **Claim Support Rate**: The fraction of extracted atomic claims classified as supported by mapped evidence chunks.
*   **Claim Contradiction Rate**: The fraction of extracted claims that conflict with case labels or mapped evidence.
*   **Claim Unverifiable Rate**: The fraction of extracted claims that cannot be checked because evidence is missing or citations point to unknown chunks.
*   **Abstention Accuracy**: Whether the model answers answerable cases and abstains on missing-evidence, contradictory, or out-of-context cases.
*   **Grounded Answer Accuracy**: Whether the answer has enough required facts, avoids forbidden facts, cites the right evidence, and abstains when required.
*   **Answer Completeness**: Keyword-level coverage of expected answer elements.

The current claim verifier is deterministic and heuristic-based. It extracts atomic claims, associates each claim with cited or lexically matched evidence chunks, and labels the claim as `supported`, `unsupported`, `contradicted`, or `unverifiable`. The verifier is implemented behind a small interface so a future NLI model or LLM judge can replace the heuristic checker without changing the evaluation output schema.

---

## Evaluation Datasets

### 1. Golden Evaluation Dataset (`backend/data/golden_evaluation_dataset.jsonl`)
*   **Type**: Synthetic Clinical Q&A
*   **Size**: 5 detailed cases (smoke test)
*   **Description**: Each case features a clinical scenario, a patient query, a list of grounded context documents, and a ground-truth answer. Used for retrieval metrics and grounded Q&A generation testing.

### 2. Synthetic Clinical QA Suite (`backend/data/synthetic_clinical_qa_180.jsonl`)
*   **Type**: Synthetic multi-hop clinical QA benchmark
*   **Size**: 180 cases by default; regenerate 100-500 cases with `scripts/generate_synthetic_eval_suite.py`
*   **Categories**: single-hop, multi-hop, temporal, contradictory, missing-evidence, and out-of-context questions.
*   **Schema**: every case includes `question`, `expected_answer`, `required_evidence_chunks`, full `evidence_chunks`, patient/tenant `scope`, `difficulty`, `failure_mode_category`, and `should_answer`.
*   **Purpose**: regression testing for retrieval targeting, citation behavior, abstention, and grounded generation.

> [!IMPORTANT]
> The synthetic QA suite is deliberately not a clinical validation set. It contains handcrafted artificial cases and deterministic labels for engineering regression tests. It should not be cited as proof of diagnostic accuracy, clinical safety, or real-world performance.

---

## How to Run Evaluations

No external API credentials are required to run the retrieval benchmarks or the RAG abstention benchmarks.

### Evaluation Categories
*   **Smoke tests**: fast checks for endpoint availability and basic evaluator wiring. These are useful for catching obvious breakage but are not quality benchmarks.
*   **Deterministic regression tests**: pytest-based checks that use fixed synthetic inputs and deterministic local retrieval behavior to guard indexing, filtering, normalization, and fusion contracts.
*   **Retrieval-quality benchmarks**: `scripts/evaluate_retrieval.py` and `scripts/evaluate_retrieval_v2.py` build temporary real dense and sparse indexes, compare dense retrieval, sparse retrieval, hybrid RRF, and optional reranked hybrid, and write versioned JSON plus Markdown artifacts. The v2 runner enforces required success gates after preserving artifacts.
*   **Live-model evaluations**: provider-backed generation or reranking checks. These are measured separately from deterministic regression tests and may depend on model availability, credentials, and network access.

### 1. Generate or Refresh the Synthetic Suite
```bash
python scripts/generate_synthetic_eval_suite.py --cases 180
```

The output defaults to `backend/data/synthetic_clinical_qa_180.jsonl`.

### 2. Run Retrieval Evaluation
Run the retrieval quality script to build a temporary index and calculate Recall, Precision, MRR, nDCG, latency, candidate-flow diagnostics, and failure counters:
```bash
python scripts/evaluate_retrieval.py
```

To evaluate the larger synthetic suite:
```bash
python scripts/evaluate_retrieval.py --dataset backend/data/synthetic_clinical_qa_180.jsonl
```

This prints a Markdown results table and saves timestamped artifacts:
*   machine-readable JSON: `results/retrieval_evaluation_results_<timestamp>.json`
*   human-readable Markdown generated from the same JSON payload: `results/retrieval_evaluation_results_<timestamp>.md`

The retrieval benchmark artifact is an engineering regression artifact. Never describe synthetic retrieval results as clinical validation, deployment safety evidence, or frontier clinical performance.

### 2a. Run Retrieval Benchmark v2
```bash
python scripts/evaluate_retrieval_v2.py
```

The current v2 default retrieval mode is `hybrid_rrf`. Required gates fail the process after JSON/Markdown artifacts are written when duplicate ratio exceeds `0.05`, cross-tenant leakage is non-zero, default-mode Recall@5 is below `0.70`, more than `0.20` of answerable queries have no expected evidence in the top 5, category metrics are missing, dataset version is missing, or commit hash is missing. The reranker latency gate is informational only.

Canonical portfolio benchmark report: `results/portfolio_gate_retrieval_benchmark_20260607T163206Z.md`. Recall@5 was dense FAISS `0.7458`, sparse retrieval `0.8417`, hybrid RRF `0.8625`, and hybrid plus rerank `0.9042`; duplicate ratio was `0.0`, and cross-tenant leakage count was `0`. Mean / p95 latency was dense FAISS `39.99 ms / 48.93 ms`, sparse retrieval `9.78 ms / 11.95 ms`, hybrid RRF `55.70 ms / 67.43 ms`, and hybrid plus rerank `244.36 ms / 287.63 ms`. On synthetic benchmark v2, hybrid RRF improves over dense and sparse retrieval. Optional reranking improves retrieval quality further but materially increases latency, so reranking remains disabled by default on latency-sensitive paths. These results are synthetic regression results, not clinical validation. Older retrieval artifacts may remain as historical baselines.

Abstention Recall@5 is reported as 0.0 by design because abstention queries have no expected evidence chunks. Retrieval recall is undefined for this category and is conservatively reported as 0.0. Abstention quality is evaluated at the generation/policy layer.

### 3. Run Grounded Generation Evaluation
Run the deterministic offline evaluator self-test. This does not require LLM provider credentials:
```bash
python scripts/evaluate_grounded_generation.py --dataset backend/data/synthetic_clinical_qa_180.jsonl --mode offline
```

Offline grounded-generation scores are evaluator infrastructure self-tests only. They are generated by feeding expected answers and expected citations back into the evaluator. They do not measure LLM answer quality.

This scores citation precision, citation recall, claim-level support/unsupported/contradiction/unverifiable rates, abstention accuracy, grounded answer accuracy, and answer completeness. Detailed JSON results are generated locally and intentionally not committed; the committed status summary is tracked in `EVALUATION_STATUS.md`.

To score real model outputs, provide a JSONL file with one answer per case:
```bash
python scripts/evaluate_grounded_generation.py \
  --dataset backend/data/synthetic_clinical_qa_180.jsonl \
  --mode answers \
  --answers-jsonl results/model_answers.jsonl
```

Each answer row must contain:
```json
{"id": "syn-multi-hop-001", "answer": "Generated answer with [syn-multi-hop-001-ev0] citations."}
```

### 4. Run Legacy RAG Smoke Evaluation
Run the existing RAG evaluator to test live RAG behavior and basic citation accuracy:
```bash
python scripts/evaluate_rag.py
```
*   If LLM credentials (`GOOGLE_API_KEY` or `GROQ_API_KEY`) are present in `backend/.env`, the script will also execute the grounded Q&A cases and evaluate citation coverage and citation accuracy.
*   If no credentials are found, it will safely run the offline verification tests (abstention accuracy and latencies) and skip the LLM-dependent tests with a warning.

Detailed results will be written to `results/rag_evaluation_results.json`.
