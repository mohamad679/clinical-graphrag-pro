# Evaluation Framework & Methodology

This document outlines the evaluation framework, metrics, and replication steps for Clinical GraphRAG Pro. The evaluation is designed to be mathematically honest and technically useful for regression testing, query pipeline optimization, and safety auditing.

> [!WARNING]
> The evaluation datasets and metrics in this repository are for demonstration and verification purposes only. They do not constitute clinical validation, and the system is not validated for diagnostic accuracy or direct patient care.

## Evaluation Metrics

We calculate two tiers of metrics: **Retrieval Metrics** and **RAG Generation Metrics**.

### 1. Retrieval Metrics
Retrieval metrics assess the quality of the candidate chunks returned by the dense (FAISS), sparse (BM25), and Hybrid retrieval engines before LLM generation.
*   **Recall@k** (k=1, 3, 5): The fraction of expected context documents successfully retrieved within the top $k$ results.
*   **Precision@k** (k=1, 3, 5): The fraction of retrieved documents within the top $k$ that are relevant.
*   **MRR (Mean Reciprocal Rank)**: Evaluates the rank of the first relevant chunk. $MRR = \frac{1}{\text{rank}_1}$ (or $0.0$ if no relevant chunk is in the top $k$).
*   **nDCG@k (Normalized Discounted Cumulative Gain)**: Evaluates ranking quality by penalizing relevant items positioned lower in the list using logarithmic discounting.
*   **Latency Profile**: Tracks retrieval time in milliseconds (Mean, Median p50, and Tail p95).

### 2. RAG Generation Metrics
Generation metrics evaluate the correctness, safety behavior, and grounding of the final synthesized answer.
*   **Abstention Accuracy**: The rate at which the system correctly returns the safe abstention response (`I do not have enough evidence in the provided documents to answer this safely.`) when queried with out-of-context or low-relevance questions.
*   **Citation Coverage**: The percentage of generated answers that contain at least one citation marker (e.g., `[SRC1]`).
*   **Citation Accuracy**: The fraction of citations in the generated answer that map back to actual retrieved chunk IDs (preventing hallucinated citations).
*   **Latency Profile**: Tracks end-to-end RAG pipeline response times (Mean, p50, p95).

---

## Evaluation Datasets

### 1. Golden Evaluation Dataset (`backend/data/golden_evaluation_dataset.jsonl`)
*   **Type**: Synthetic Clinical Q&A
*   **Size**: 5 detailed cases (smoke test)
*   **Description**: Each case features a clinical scenario, a patient query, a list of grounded context documents, and a ground-truth answer. Used for retrieval metrics and grounded Q&A generation testing.

---

## How to Run Evaluations

No external API credentials are required to run the retrieval benchmarks or the RAG abstention benchmarks.

### 1. Run Retrieval Evaluation
Run the retrieval quality script to build a temporary index and calculate Recall, Precision, MRR, nDCG, and Latency:
```bash
python scripts/evaluate_retrieval.py
```

This will print a Markdown results table and save the raw JSON output to `results/retrieval_evaluation_results.json`.

### 2. Run RAG Generation Evaluation
Run the RAG evaluator to test abstention behavior and citation accuracy:
```bash
python scripts/evaluate_rag.py
```
*   If LLM credentials (`GOOGLE_API_KEY` or `GROQ_API_KEY`) are present in `backend/.env`, the script will also execute the grounded Q&A cases and evaluate citation coverage and citation accuracy.
*   If no credentials are found, it will safely run the offline verification tests (abstention accuracy and latencies) and skip the LLM-dependent tests with a warning.

Detailed results will be written to `results/rag_evaluation_results.json`.
