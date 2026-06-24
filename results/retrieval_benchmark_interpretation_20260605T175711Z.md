# Retrieval Benchmark Interpretation - 20260605T175711Z

## Artifacts

- Baseline, sandboxed model resolution: `results/retrieval_benchmark_baseline_20260605T170816Z.json`
- Baseline, network-enabled model/reranker resolution: `results/retrieval_benchmark_baseline_network_20260605T172807Z.json`
- Final repaired benchmark: `results/retrieval_evaluation_results_20260605T175711Z.json`

## Benchmark Context

- Dataset: `backend/data/synthetic_clinical_qa_180.jsonl`
- Dataset SHA-256: `a5ecd4e5ca3256828c5ed02ab2df057b7e6241b48516f818662ac3c0f2424477`
- Answerable query count: 90
- Abstention-only cases skipped for retrieval metrics: 90
- Corpus chunk count: 180
- Random seed: 20260605
- Embedding model: `sentence-transformers/all-mpnet-base-v2`
- Embedding dimension: 768
- Chunk size / overlap: 512 / 64
- Retrieval scope: `tenant_id=demo-tenant`, `patient_id=pat-100`, `user_id=user-123`
- Git commit: `56d27be7a558e8d53596da1ec2f245c00cb83d86`
- Final working-tree status SHA-16: `3a5671b727799bde`

## Root Cause

BM25 indexing was running and the sparse corpus was non-empty, but sparse metadata did not include the same authorization scope used by dense retrieval and evaluation. Baseline BM25 metadata included `user_id`, but not `tenant_id` or `patient_id`. Exact sparse scope filtering therefore removed every BM25 candidate for scoped benchmark queries. RRF received no sparse candidates, so hybrid retrieval behaved like dense FAISS.

The production document-processing path had the same mismatch: dense vector chunks received richer scope metadata, while BM25 indexing only received `user_id`.

## Baseline Metrics

From `results/retrieval_benchmark_baseline_network_20260605T172807Z.json`:

| Method | MRR | P@1 | R@1 | R@3 | R@5 | NDCG@5 | Sparse mean | Dense mean | Merged mean | No results | No relevant @5 | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FAISS Only | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0 | 5.0 | 0.0 | 0 | 45 | 53.43 | 61.80 |
| BM25 Only | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0 | 0.0 | 0.0 | 90 | 90 | 1.25 | 1.76 |
| Hybrid FAISS + BM25 + RRF | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0 | 15.0 | 15.0 | 0 | 45 | 55.59 | 68.74 |
| Hybrid + Rerank | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0 | 15.0 | 15.0 | 0 | 45 | 49.82 | 175.53 |

Baseline BM25 state: 180 memory documents, 180 non-empty documents, 3,129 tokens, vocabulary size 124, and zero sparse candidates after scoped filtering.

## Final Repaired Metrics

From `results/retrieval_evaluation_results_20260605T175711Z.json`:

| Method | MRR | P@1 | R@1 | R@3 | R@5 | NDCG@5 | Sparse mean | Dense mean | Merged mean | No results | No relevant @5 | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FAISS Only | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0 | 5.0 | 0.0 | 0 | 45 | 56.72 | 98.27 |
| BM25 Only | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 5.0 | 0.0 | 0.0 | 0 | 45 | 1.91 | 5.04 |
| Hybrid FAISS + BM25 + RRF | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 15.0 | 15.0 | 21.63 | 0 | 45 | 68.63 | 79.29 |
| Hybrid + Rerank | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 15.0 | 15.0 | 21.63 | 0 | 45 | 101.06 | 337.19 |

Final BM25 state: 180 total documents, 180 active documents, 3,482 tokens, vocabulary size 146, 0 empty documents, and 156 duplicate-normalized documents.

## Interpretation

The sparse branch is repaired: BM25-only no longer has zero candidates or no-result failures, and hybrid RRF now receives real dense and sparse candidate lists.

The measured ranking quality did not improve. BM25-only, FAISS-only, hybrid, and hybrid with reranking all produced the same MRR, precision, recall, and NDCG on this synthetic dataset. This benchmark does not support claiming that hybrid retrieval is better than FAISS for the current dataset and configuration.

The high duplicate-normalized document count is consistent with repeated synthetic clinical templates and evidence patterns. That likely limits the ability of lexical, dense, or fused retrieval to distinguish case-specific evidence. Hybrid retrieval is operationally healthy after the fix, but it should remain measured rather than assumed beneficial.
