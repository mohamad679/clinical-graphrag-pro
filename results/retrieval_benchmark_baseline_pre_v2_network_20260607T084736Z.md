# Retrieval Benchmark Report - 20260607T084835Z

This is a synthetic retrieval-quality regression benchmark. It is not clinical validation,
not a deployment safety claim, and not evidence of SOTA clinical performance.

## Run Metadata

- Artifact schema: `retrieval-benchmark-v2`
- Benchmark category: `retrieval-quality benchmark`
- Seed: `20260605`
- Dataset: `backend/data/synthetic_clinical_qa_180.jsonl`
- Dataset SHA-256: `a5ecd4e5ca3256828c5ed02ab2df057b7e6241b48516f818662ac3c0f2424477`
- Query count: 90
- Skipped abstention-only cases: 90
- Git commit: `56d27be7a558e8d53596da1ec2f245c00cb83d86`
- Git branch: `main`
- Working-tree status SHA-16: `b66ccfe97693b852`
- Backend mode: `temporary-faiss-and-in-memory-bm25`
- Vector backend: `faiss`
- Sparse backend: `memory-rank-bm25`
- Embedding model: `sentence-transformers/all-mpnet-base-v2`
- Corpus chunks: 180
- BM25 token count: 3482
- BM25 vocabulary size: 146

## Metrics

| Method | MRR | P@1 | R@1 | R@3 | R@5 | NDCG@5 | Zero-result rate | Empty-index failures | Auth-filter rejections | p50 ms | p95 ms | p99 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FAISS Only | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0000 | 0 | 0 | 77.87 | 106.90 | 170.54 |
| BM25 Only | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0000 | 0 | 0 | 1.94 | 2.43 | 2.67 |
| Hybrid (FAISS + BM25 + RRF) | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0000 | 0 | 0 | 92.09 | 180.43 | 290.96 |
| Hybrid + Rerank | 0.2283 | 0.1000 | 0.0648 | 0.1944 | 0.3241 | 0.2126 | 0.0000 | 0 | 0 | 67.03 | 273.70 | 542.53 |

## Candidate Flow

| Method | Dense mean | Sparse mean | Merged mean | Reranked queries |
| --- | ---: | ---: | ---: | ---: |
| FAISS Only | 5.00 | 0.00 | 0.00 | 0 |
| BM25 Only | 0.00 | 5.00 | 0.00 | 0 |
| Hybrid (FAISS + BM25 + RRF) | 15.00 | 15.00 | 21.63 | 0 |
| Hybrid + Rerank | 15.00 | 15.00 | 21.63 | 90 |

## Interpretation Guardrail

Only claim improvement when the measured metrics above improve. If hybrid or reranked
retrieval matches dense retrieval while adding latency, report that directly.
