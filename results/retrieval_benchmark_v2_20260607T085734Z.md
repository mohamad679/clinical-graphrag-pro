# Retrieval Benchmark v2 Report - 20260607T085736Z

Synthetic retrieval regression benchmark only. This is not clinical validation or SOTA evidence.

## Dataset

- Version: `synthetic_retrieval_benchmark_v2`
- Queries: 135
- Corpus chunks: 195
- Duplicate ratio: 0.0000
- Seed: 20260607

## Overall Metrics

| Mode | MRR | R@1 | R@3 | R@5 | P@5 | nDCG@5 | Abstention acc. | Leakage | Mean ms | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 0.4589 | 0.2250 | 0.5750 | 0.7458 | 0.1833 | 0.5204 | 0.0000 | 0 | 49.24 | 47.67 | 64.54 | 68.52 |
| sparse | 0.5414 | 0.3333 | 0.7000 | 0.8417 | 0.1917 | 0.6204 | 0.0000 | 0 | 12.44 | 11.09 | 14.66 | 26.56 |
| hybrid_rrf | 0.5954 | 0.3667 | 0.7292 | 0.8625 | 0.2017 | 0.6545 | 0.0000 | 0 | 54.34 | 53.45 | 58.53 | 64.91 |
| hybrid_plus_rerank | 0.6779 | 0.4333 | 0.8042 | 0.9042 | 0.2200 | 0.7259 | 0.0000 | 0 | 493.15 | 181.18 | 290.67 | 366.53 |

## Category Recall@5

| Category | Dense | Sparse | Hybrid | Rerank |
| --- | ---: | ---: | ---: | ---: |
| abstention | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| contradiction | 0.5500 | 0.0000 | 0.3000 | 0.8500 |
| cross_tenant_leakage_attempt | 0.3333 | 0.4667 | 0.5333 | 0.4667 |
| graph_dependent | 0.3000 | 1.0000 | 0.8000 | 0.8000 |
| hard_negative | 0.9500 | 1.0000 | 1.0000 | 1.0000 |
| lexical_exact | 0.9333 | 1.0000 | 1.0000 | 1.0000 |
| medication_dosage_unit | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| negation | 0.6000 | 1.0000 | 1.0000 | 1.0000 |
| semantic_paraphrase | 0.8000 | 1.0000 | 1.0000 | 1.0000 |
| temporal_question | 1.0000 | 0.9333 | 0.9667 | 1.0000 |

## Success Gates

- duplicate_ratio_lte_0_05: `True`
- sparse_index_non_empty: `True`
- cross_tenant_leakage_zero_all_modes: `True`
- hybrid_claim_supported: `True`
- rerank_latency_justified: `False`
