# Clinical GraphRAG Pro: Technical System Paper

## Abstract
Clinical question answering fails when systems miss exact medical terms, ignore timeline constraints, or answer without traceable evidence. We built Clinical GraphRAG Pro as an integration of FastAPI, hybrid retrieval (FAISS + BM25 + reciprocal rank fusion), a temporal knowledge graph, and an agent loop with verification. Retrieval and fusion are implemented in `backend/app/services/vector_store.py`, `backend/app/services/bm25_index.py`, and `backend/app/services/query_engine.py`; temporal graph persistence is in `backend/app/services/graph.py` and `backend/app/models/persistence.py`; and verification is in `backend/app/services/agent.py` via `clinical_eval` in `backend/app/services/tool_registry.py`. In the committed benchmark artifact dated 2026-04-02 (`results/benchmark_2026.json`), FAISS, BM25, and Hybrid reached 100% keyword and top-5 hit rates on 20 retrieval pairs, with mean latencies 17.094 ms, 0.311 ms, and 14.733 ms. The MedQA section failed due provider authentication, so no MedQA accuracy is reported.

## 1. Introduction

### 1.1 Problem Statement
Clinical QA is not only a language-generation problem. In this setting, the main failure modes are retrieval and grounding failures: answers can be fluent but anchored to incorrect evidence, wrong dates, or no auditable source. A missed dosage token or ambiguous abbreviation can materially change clinical interpretation. We therefore frame the task as constrained evidence synthesis.

This imposes four requirements: chunk-level attribution, robust lexical+semantic retrieval, explicit temporal filtering, and calibrated uncertainty handling with rejection behavior when evidence is insufficient. Clinical GraphRAG Pro is an integration of established methods (RAG, BM25, RRF, reranking, temporal graph filtering), with emphasis on explicit interfaces and measurable behavior rather than algorithmic novelty.

### 1.2 System Overview
At a high level, the browser streams user queries to FastAPI, retrieval and graph services build bounded evidence, and LLM services synthesize responses with citations and heuristic evidence-support markers.

```text
Browser UI (Web Components)
        |
      nginx
        |
   FastAPI API Layer
   |      |       |
 Chat   Agents   Images
   |      |       |
   +--- RAG Orchestrator ---+
           |                |
      Query Engine      Temporal Graph
   (FAISS + BM25 +      (GraphNode/Edge,
      RRF + rerank)      optional Neo4j)
           |
      LLM Service
   (Groq primary, Gemini fallback)
```

### 1.3 Contributions
We contribute four implemented components: (1) rank-based dense+sparse fusion with configurable reranking (`query_engine.py`, `config.py`), (2) persistent temporal graph queries over dated edges (`graph.py`), (3) a plan-execute-synthesize-verify agent loop (`agent.py`), and (4) reproducible benchmark scripts with JSON artifacts (`backend/scripts/benchmark_retrieval.py`, `backend/scripts/run_benchmark.py`).

## 2. Retrieval Architecture

### 2.1 Dense Retrieval
Dense retrieval is implemented in `FAISSBackend` (`backend/app/services/vector_store.py`). The system uses sentence-transformer embeddings and a FAISS `IndexFlatIP` index. Because embeddings are normalized at index and query time, inner product behaves as cosine similarity. Chunking is sentence-aware with defaults `chunk_size=512` and `chunk_overlap=64` (`backend/app/core/config.py`).

We chose flat search for deterministic behavior and low operational complexity. This is acceptable for current corpus size but remains linear-scan. A second limitation is embedding-version drift: config defaults to `all-mpnet-base-v2`, while committed benchmark artifacts show runs with `all-MiniLM-L6-v2`.

### 2.2 Sparse Retrieval
Sparse retrieval is implemented in `backend/app/services/bm25_index.py`. In database mode, it uses PostgreSQL FTS over persisted `DocumentChunk` rows; in in-memory mode, it uses `rank-bm25` (or token-overlap fallback). This path is strong for exact lexical anchors (drug names, lab terms, abbreviations). Tokenization (`\b[\w-]+\b`) is conservative and practical, but ambiguity such as MI remains unresolved.

### 2.3 Reciprocal Rank Fusion
Fusion occurs in `QueryEngine._rrf_merge` (`backend/app/services/query_engine.py`). Conceptually:

$$
RRF(d) = \sum_{r \in R} \frac{1}{k + r(d)}
$$

where \(R\) is the set of rankings, \(r(d)\) is rank position, and \(k=60\). We use RRF because FAISS and BM25 scores are not directly comparable; rank-based fusion avoids score-scale brittleness. The implementation is in `_rrf_merge` (`backend/app/services/query_engine.py`) and follows the same practical intuition as Cormack et al. (2009). The code uses zero-based ranks internally, which changes constants slightly but not the core ordering behavior.

### 2.4 Cross-Encoder Reranking
Reranking is handled by `backend/app/services/reranker.py` and called when `use_reranking=True`. The configured model is `cross-encoder/ms-marco-MiniLM-L-6-v2`. The pipeline retrieves broader candidates quickly (`fetch_k = top_k * 3`) and reranks a short list. This improves ordering in ambiguous queries but adds significant latency; in committed benchmarks, reranking dominates retrieval compute.

### 2.5 Retrieval Evaluation
We use two artifacts: `docs/benchmark_results.json` (2026-04-01, 5-case ablation) and `results/benchmark_2026.json` (2026-04-02, 20 retrieval pairs). For the four-mode table below, keyword hit rate is computed from per-query keyword lists in the 2026-04-01 artifact.

| Method | Keyword Hit Rate | Latency |
|--------|------------------|---------|
| FAISS only | 100.0% | 18.898 ms |
| BM25 only | 100.0% | 0.294 ms |
| Hybrid + RRF | 100.0% | 16.450 ms |
| Hybrid + Reranking | 100.0% | 242.471 ms |

In the same artifact, Precision@5 is 0.36 for all modes; MRR is 1.0 for FAISS/Hybrid/Reranked and 0.9 for BM25.

## 3. Knowledge Graph Layer

### 3.1 Graph Schema
The graph schema is formalized in `FORMAL_GRAPH_SCHEMA` (`backend/app/services/graph.py`) and persisted through SQLAlchemy models `GraphNode` and `GraphEdge` (`backend/app/models/persistence.py`). The current schema includes 9 node labels and 8 relationship types:

- Node labels: Patient, Encounter, Document, Condition, Symptom, Medication, Lab, ImagingStudy, Finding.
- Relationship types: HAS_CONDITION, HAS_LAB, TOOK_MEDICATION, HAS_FINDING, LAB_RESULT, MENTIONED_IN, OCCURRED_AT, RELATED_TO.

Temporal state is represented directly on edges (`start_date`, `end_date`) plus source metadata in `properties`.

Example subgraph:

```text
[Patient_A] --TOOK_MEDICATION {start: 2023-11-01, dose: 10mg}--> [Lisinopril]
[Lisinopril] --RELATED_TO--> [Hypertension]
[Patient_A] --LAB_RESULT {date: 2024-01-15, value: 54, unit: mL/min/1.73m2}--> [eGFR]
```

### 3.2 Temporal Reasoning
Point-in-time reasoning is exposed through `query_temporal_state` (`backend/app/services/graph.py`) and `/api/graph/temporal` (`backend/app/api/graph.py`). The service validates ISO dates, resolves an entity in scoped nodes, then filters incident edges with `_is_active_on_date`:

- inactive if `target_date < start_date`
- inactive if `target_date > end_date`
- otherwise active

This supports queries like: “What medications was this patient on in March 2023?” The same layer provides lab trend extraction with chronological sorting (`get_lab_trends` and `/api/graph/patients/{patient_id}/lab-trends`).

### 3.3 Graph vs Retrieval Complementarity
Graph and retrieval answer different question classes:

- Graph wins on temporal and relational constraints (“which meds were active on date X?”, “what labs trended for patient Y?”).
- Retrieval wins on narrative detail and free-text evidence not normalized into graph entities.

In the agent path, tool choice is generated in planning (`_generate_plan` in `backend/app/services/agent.py`) from `tool_registry` schemas.

## 4. Agent Architecture

### 4.1 Plan-Execute-Reflect Loop
The orchestrator (`backend/app/services/agent.py`) is implemented as a LangGraph state machine with four nodes: plan, execute, synthesize, verify. Operationally:

1. **Plan**: generate an ordered step list and tool calls from the user query.
2. **Execute**: run each tool call, persist result and latency, and emit SSE events.
3. **Synthesize**: build a draft answer from structured tool evidence.
4. **Verify**: run adjudication; approve or reject; optionally retry synthesis once.

A typical `/api/agents/run` trace is `workflow_start -> reasoning -> tool_call -> tool_result -> synthesis -> verification -> workflow_complete`.

### 4.2 Tool Registry
Tools are centrally registered in `backend/app/services/tool_registry.py`. Current tool surface and intended usage:

- `search_documents`: vector-store retrieval over uploaded chunks.
- `search_graph`: date-scoped graph relationship lookup.
- `query_clinical_graph`: bounded natural-language graph query path (Neo4j helper).
- `medical_calculator`: currently BMI, eGFR, CHA2DS2-VASc (HEART score is not implemented in current code).
- `pubmed_search`: NCBI E-utilities lookup for recent literature metadata.
- `drug_interaction`: OpenFDA event-driven signal plus RxNorm concept enrichment.
- `analyze_image`: vision analysis over uploaded medical images.
- `clinical_eval`: adjudicator for groundedness and safety checks.
- `normalize_entities`: canonical mapping through entity normalization service.

### 4.3 Red Team Adjudicator
The verification step calls `clinical_eval` before finalizing an answer (`verify_node` in `backend/app/services/agent.py`). The adjudicator returns JSON (`status`, `confidence_score`, `flags`). If rejected, synthesis is retried with flags; after retry budget exhaustion, the workflow returns a refusal-style answer. This is a guardrail, not a formal safety guarantee.

## 5. Clinical Safety Considerations

### 5.1 PHI Handling
In the current main branch, PHI handling is strongest on the image path, not unstructured text. DICOM uploads go through `scrub_dicom` (`backend/app/services/dicom_scrubber.py`), which removes defined PHI tags and converts pixel data to sanitized PNG bytes; non-DICOM uploads apply metadata stripping in `image_processing.py`. We did not find a Presidio text-redaction pipeline in `backend/app`, so text-path PHI controls remain incomplete for clinical deployment.

### 5.2 Source Attribution
Source attribution is chunk-level. The RAG layer assigns citation IDs, builds context sections with chunk metadata, and parses citation markers back from output (`_assign_citation_ids`, `_build_context_text`, `_parse_citations` in `rag.py`). If citations are missing, `_ensure_citation_footer` appends fallback markers. “Verified” means marker-to-chunk traceability, not clinical correctness.

### 5.3 Uncertainty Quantification
The LLM prompt requires `[CONFIDENCE: x.xx]` (`llm.py`, `rag.py`). Backend parsing extracts and strips this marker (`_extract_confidence`, `_strip_confidence_marker`), with defaults 0.82 (with context) or 0.25 (without context). Frontend displays the value through `extractConfidence` and `renderConfidenceBadge` (`frontend/public/js/components/chat-interface.js`). This remains self-reported uncertainty, not a calibrated probability.

### 5.4 Explicit Disclaimer
The project includes explicit decision-support language in configuration and UI (`disclaimer_text` in `backend/app/core/config.py`; disclaimer banner in chat UI). We state this clearly for any external reader:

- This system is **not** a medical device.
- It is **not** HIPAA certified.
- It is intended for research, engineering demonstration, and educational evaluation.

## 6. Evaluation

### 6.1 MedQA Benchmark
`backend/scripts/run_benchmark.py` defines a 100-question synthetic MedQA-style dataset (`backend/app/data/benchmarks/medqa_100.jsonl`) and evaluates direct LLM vs RAG-augmented answers at `temperature=0`.

Committed result status (artifact dated 2026-04-02, `results/benchmark_2026.json`):

| Metric | Value |
|--------|-------|
| Questions requested | 100 |
| Questions evaluated | 0 |
| Direct accuracy | N/A |
| RAG accuracy | N/A |
| Failure mode | Provider auth error (Groq 401, Gemini 403) |

This is still a valid benchmark outcome because the script records failure honestly rather than fabricating numbers.

### 6.2 RAG Quality Metrics
The repository has two retrieval-quality paths: (1) keyword-hit benchmarking on 20 retrieval pairs (`run_benchmark.py`), and (2) 4-mode ablation on the 5-case golden dataset (`benchmark_retrieval.py`). RAGAS integration exists in `backend/scripts/evaluate_ragas.py` with:

- **Faithfulness**: whether answer claims are grounded in retrieved context.
- **Answer relevancy**: whether the answer addresses the user question.
- **Context precision**: whether retrieved chunks are relevant to the question.

Committed artifacts currently emphasize retrieval metrics; a reproducible credential-stable RAGAS artifact is not committed.

### 6.3 Latency Profile
From `docs/benchmark_results.json` (2026-04-01):

- Embedding generation: avg 14.566 ms
- FAISS top-k vector search: avg 0.051 ms
- BM25 search: avg 0.320 ms
- RRF fusion: avg 0.013 ms
- Cross-encoder rerank (top-5): avg 127.844 ms

Model loading is a major one-time cost:

- Embedding model load: 18,366.941 ms
- Reranker model load: 3,553.695 ms

Retrieval compute is fast; reranking materially changes latency budgets. End-to-end MedQA latency is unavailable in the committed run because provider authentication failed before generation.

## 7. Implementation Notes

### 7.1 Technology Choices
Major choices are FastAPI async + SQLAlchemy async, FAISS+BM25 hybrid retrieval with RRF, optional cross-encoder reranking, relational temporal graph with optional Neo4j sync, and safe-buffered SSE-first frontend streaming (`main.py`, `query_engine.py`, `graph.py`, `api/chat.py`).

For concise decision records, see `docs/decisions/ADR-001-hybrid-retrieval.md` through `docs/decisions/ADR-005-groq-gemini-fallback.md`.

### 7.2 Deployment
The repository supports three paths: full local stack via `docker-compose.yml`; Hugging Face Space backend deployment via `backend/deploy_hf.sh`; and local frontend with remote backend proxy via `scripts/run_frontend_local.py`.

### 7.3 Limitations and Future Work
Current technical limitations:

1. The default embedding choice is general-purpose, not clinically pretrained (`embedding_model` setting in `config.py`).
2. The golden retrieval benchmark corpus is tiny (`n=5` cases in `golden_evaluation_dataset.jsonl`), so variance is high.
3. The MedQA benchmark artifact currently has no accuracy output due invalid provider credentials at run time.
4. Graph quality depends on ingested entities and seeded/demo inputs; there is no live EHR integration path in main branch.
5. Mainline deployment remains effectively single-tenant from an operational governance perspective, despite per-user/tenant scoping in several services.
6. There is no formal clinical validation protocol with physician reviewers committed to the repository.
7. Text-path PHI redaction via Presidio is not implemented in current backend code.
8. Graph reasoning is bounded by explicit edges and does not provide broad probabilistic inference.

Future work with highest expected impact:

- Replace general embedding models with biomedical embeddings (e.g., PubMedBERT-derived retrieval encoders) and re-benchmark.
- Add HL7 FHIR R4 ingestion and mapping into graph/document stores.
- Run clinician-reviewed evaluation with blinded scoring for groundedness and safety usefulness.
- Harden true multi-tenant isolation at storage, job, and retrieval boundaries.

## 8. Conclusion
Clinical GraphRAG Pro integrates hybrid retrieval, temporal graph querying, and guarded generation into one inspectable system with benchmark artifacts. The evidence supports three points. First, retrieval-stage compute is efficient, while reranking is the major latency cost. Second, rank-based fusion is easier to operate than score-normalization approaches when dense and sparse score scales differ. Third, transparent failure reporting is essential: the committed MedQA run failed from provider authentication, and we report that directly. The system is therefore credible as an engineering prototype, but not ready for clinical deployment claims without stronger PHI controls, larger datasets, and formal clinician validation.

## References
1. Lewis, P., Perez, E., Piktus, A., et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *NeurIPS 2020*.
2. Robertson, S., & Zaragoza, H. (2009). The Probabilistic Relevance Framework: BM25 and Beyond. *Foundations and Trends in Information Retrieval*, 3(4), 333-389.
3. Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009). Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods. *SIGIR 2009*.
4. Es, S., James, J., Espinosa Anke, L., & Schockaert, S. (2023). RAGAS: Automated Evaluation of Retrieval Augmented Generation. *arXiv preprint arXiv:2309.15217*.
5. Johnson, J., Douze, M., & Jégou, H. (2019). Billion-scale Similarity Search with GPUs. *IEEE Transactions on Big Data*, 7(3), 535-547.
6. Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks. *EMNLP-IJCNLP 2019*.
7. Jin, D., Pan, E., Oufattole, N., et al. (2021). What Disease Does This Patient Have? A Large-scale Open Domain Question Answering Dataset from Medical Exams. *Applied Sciences*, 11(14), 6421.
8. Jin, Q., Dhingra, B., Liu, Z., Cohen, W. W., & Lu, X. (2019). PubMedQA: A Dataset for Biomedical Research Question Answering. *EMNLP-IJCNLP 2019*.
9. Neumann, M., King, D., Beltagy, I., & Ammar, W. (2019). ScispaCy: Fast and Robust Models for Biomedical Natural Language Processing. *BioNLP Workshop at ACL 2019*.
10. HL7 International. (2019). *FHIR Release 4 (v4.0.1): HL7 Fast Healthcare Interoperability Resources*.
