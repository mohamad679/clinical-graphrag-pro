# Retrieval Benchmark v2 Report - 20260608T063202Z

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
| dense | 0.4589 | 0.2250 | 0.5750 | 0.7458 | 0.1833 | 0.5204 | 0.0000 | 0 | 56.31 | 54.22 | 72.24 | 77.78 |
| sparse | 0.5414 | 0.3333 | 0.7000 | 0.8417 | 0.1917 | 0.6204 | 0.0000 | 0 | 15.16 | 14.00 | 21.50 | 32.22 |
| hybrid_rrf | 0.5954 | 0.3667 | 0.7292 | 0.8625 | 0.2017 | 0.6545 | 0.0000 | 0 | 121.22 | 76.80 | 202.50 | 1460.70 |
| hybrid_plus_rerank | 0.6779 | 0.4333 | 0.8042 | 0.9042 | 0.2200 | 0.7259 | 0.0000 | 0 | 734.51 | 393.42 | 501.70 | 597.98 |

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
- cross_tenant_leakage_count_eq_0: `True`
- default_mode_recall_at_5_gte_0_70: `True`
- answerable_queries_without_expected_evidence_in_top_5_rate_lte_0_20: `True`
- category_metrics_present: `True`
- dataset_version_present: `True`
- commit_hash_present: `True`
- hybrid_claim_supported: `True`
- rerank_latency_justified: `False`

- default_retrieval_mode: `hybrid_rrf`
- required_gate_status: `passed`
- required_gate_failures: `none`
- reranker_latency_justified: `False` (informational only)
