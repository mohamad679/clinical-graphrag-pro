# Benchmark Results

## Overview
Clinical GraphRAG Pro was evaluated on 2026-04-02 using gemini-2.0-flash.
MedQA was not completed because the configured LLM credentials were not accepted by the provider.
Retrieval keyword hit rates were FAISS 100.0%, BM25 100.0%, and Hybrid 100.0%.

## MedQA Status
| Category | Direct Accuracy | RAG Accuracy |
| --- | ---: | ---: |
| N/A | N/A | N/A |

## RAG vs Direct LLM
| Category | Direct Accuracy | RAG Accuracy | Delta |
| --- | ---: | ---: | ---: |
| N/A | N/A | N/A | N/A |

## Retrieval Quality
| Method | Keyword Hit Rate | Top-5 Hit Rate | Mean Latency (ms) |
| --- | ---: | ---: | ---: |
| FAISS only | 100.0% | 100.0% | 32.004 |
| BM25 only | 100.0% | 100.0% | 0.418 |
| Hybrid + RRF | 100.0% | 100.0% | 24.354 |

## Methodology
- Dataset: 100 original clinical MCQ questions
- Split: Cardiology 20, Endocrinology 20, Nephrology 15, Pharmacology/Drug interactions 15, Pulmonology 15, Hematology 15
- Model: gemini-2.0-flash
- Temperature: 0 (deterministic)
- RAG: top-3 dense retrieval for MedQA prompt augmentation; top-5 hybrid retrieval with RRF fusion for retrieval-quality scoring

## Limitations
- Questions are synthetic, not from an official USMLE or MedQA release.
- Evaluation was conducted on 2026-04-02; results may vary with different indexed documents.
- The currently indexed retrieval corpus is whatever chunk artifacts were present locally at runtime.
- MedQA requires valid external LLM credentials; if provider auth fails, the benchmark reports that failure instead of fabricating accuracy.
- Retrieval hit-rate scoring is keyword based and does not replace physician review of answer quality.
