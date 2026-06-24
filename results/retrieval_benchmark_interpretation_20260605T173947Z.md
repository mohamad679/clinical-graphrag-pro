# Retrieval Benchmark Interpretation - 20260605T173947Z

## Artifacts

- Baseline, sandboxed model resolution: `results/retrieval_benchmark_baseline_20260605T170816Z.json`
- Baseline, network-enabled reranker/model resolution: `results/retrieval_benchmark_baseline_network_20260605T172807Z.json`
- Repaired benchmark: `results/retrieval_evaluation_results_20260605T173947Z.json`

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
- Repaired working-tree status SHA-16: `0694522c16780511`

## Root Cause

BM25 index construction was invoked and the sparse corpus was not empty, but the BM25 metadata did not include the same authorization scope fields used by dense retrieval and evaluation. Baseline BM25 metadata included `user_id`, but not `tenant_id` or `patient_id`. Because sparse search applies exact scope filtering, every BM25 candidate was filtered out for benchmark queries scoped by tenant and patient. RRF then received no sparse candidates, so hybrid retrieval reduced to dense FAISS behavior.

The same metadata mismatch existed in the production document-processing path: dense vector chunks received richer scope metadata, while BM25 indexing only received `user_id`.

## Baseline Metrics

From `results/retrieval_benchmark_baseline_network_20260605T172807Z.json`:

| Method | MRR | P@1 | R@1 | R@3 | R@5 | NDCG@5 | Sparse mean | Dense mean | Merged mean | No results | No relevant @5 | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FAISS Only | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0 | 5.0 | 0.0 | 0 | 45 | 53.43 | 61.80 |
| BM25 Only | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0 | 0.0 | 0.0 | 90 | 90 | 1.25 | 1.76 |
| Hybrid FAISS + BM25 + RRF | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0 | 15.0 | 15.0 | 0 | 45 | 55.59 | 68.74 |
| Hybrid + Rerank | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0 | 15.0 | 15.0 | 0 | 45 | 49.82 | 175.53 |

Baseline BM25 state: 180 memory documents, 180 non-empty documents, 3,129 tokens, vocabulary size 124, and zero sparse candidates after scoped filtering.

## Repaired Metrics

From `results/retrieval_evaluation_results_20260605T173947Z.json`:

| Method | MRR | P@1 | R@1 | R@3 | R@5 | NDCG@5 | Sparse mean | Dense mean | Merged mean | No results | No relevant @5 | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FAISS Only | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0 | 5.0 | 0.0 | 0 | 45 | 53.25 | 58.80 |
| BM25 Only | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 5.0 | 0.0 | 0.0 | 0 | 45 | 1.19 | 1.64 |
| Hybrid FAISS + BM25 + RRF | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 15.0 | 15.0 | 21.63 | 0 | 45 | 64.83 | 70.93 |
| Hybrid + Rerank | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 15.0 | 15.0 | 21.63 | 0 | 45 | 66.58 | 250.18 |

Repaired BM25 state: 180 total documents, 180 active documents, 3,482 tokens, vocabulary size 146, 0 empty documents, and 156 duplicate-normalized documents.

## Interpretation

The sparse branch is repaired: BM25-only no longer has zero candidates or no-result failures, and hybrid RRF now receives real dense and sparse candidate lists.

The measured ranking quality did not improve. BM25-only, FAISS-only, hybrid, and hybrid with reranking all produced the same MRR, precision, recall, and NDCG on this synthetic dataset. Therefore this benchmark does not support claiming that hybrid retrieval is better than FAISS for the current dataset and configuration.

The duplicate-normalized document count is high because the synthetic dataset repeats clinical question templates and evidence patterns. That appears to limit the ability of either lexical or dense retrieval to distinguish the intended case-specific evidence. Hybrid retrieval is operationally healthy after the fix, but it should remain measured rather than assumed beneficial.
