# Clinical GraphRAG Pro: A Multi-Modal Retrieval-Augmented Generation System
for Grounded Clinical Decision Support

Author: Mohammad Javad Asgari  
Institution: Politecnico di Torino  
Date: March 2026  
Repository: https://github.com/mohamad679/clinical-graphrag-pro  
Status: Technical Report / Portfolio Project

---

## 1. Abstract

Clinical decision support systems must retrieve, organize, and summarize information from heterogeneous records that are often fragmented across narrative notes, structured findings, medication histories, laboratory results, and imaging studies. In such settings, an answer can fail even when the language model is fluent: the central failure mode is not poor prose but retrieval error, temporal inconsistency, or unsupported synthesis. Clinical GraphRAG Pro addresses this problem through a retrieval-augmented architecture in which a FastAPI backend coordinates hybrid text retrieval, a temporal knowledge graph, and a bounded answer-construction layer that requires explicit citations and an end-of-answer heuristic evidence-support marker. The implementation combines a query engine for optional query expansion, dense retrieval over a FAISS index, sparse retrieval over a BM25-style layer, reciprocal-rank fusion, and optional cross-encoder reranking before context reaches the answer generator. The same repository also contains a graph service with temporal edges, an agent orchestration loop with an explicit verification stage, and a Gemini-backed medical-image analysis path, thereby making the system multimodal rather than text-only. Evaluation is likewise multi-layered: the repository includes a small golden dataset for RAGAS-based faithfulness-oriented evaluation and a separate internal quality suite with seven release baselines. The system nevertheless remains a research-oriented portfolio artifact rather than a deployable clinical product. Its bundled evaluation dataset contains only five golden questions, the repository ships demo rather than hospital-connected data, no prospective clinical validation study is encoded in the project, and the security/compliance primitives implemented in code do not constitute HIPAA compliance. (Code: `backend/app/main.py`, `backend/app/services/rag.py`, `backend/app/services/query_engine.py`, `backend/app/services/graph.py`, `backend/app/services/agent.py`, `backend/app/services/vision.py`, `backend/app/services/evaluation_runner.py`, `backend/scripts/evaluate_ragas.py`, `backend/data/golden_evaluation_dataset.jsonl`, `scripts/demo/seed_demo_data.py`)

---

## 2. Introduction

Clinical AI systems fail in materially different ways from consumer assistants. In a clinical setting, an incorrect answer is not merely unhelpful; it can distort medication reconciliation, hide a contraindication, or misstate the chronology of events that determines whether a treatment remains appropriate. The RAG literature already frames retrieval as a grounding mechanism for knowledge-intensive tasks [1], but the clinical version of the problem is sharper because an answer that cites the wrong passage may still sound internally coherent. The current repository encodes this concern directly: the core answer prompts instruct the model to answer only from grounded context, cite evidence using in-context citation markers, emit a heuristic evidence-support marker, and require clinician review for demo output; if sufficiently grounded evidence is absent, the service falls back to an explicit safety disclaimer rather than attempting open-ended completion. That design choice is visible not in prose alone but in the answer-building path itself. (Code: `backend/app/services/llm.py`, `backend/app/services/rag.py`, `backend/app/core/config.py`, `backend/app/api/health.py`)

The underlying retrieval problem is also not purely semantic. Clinical questions frequently mix paraphrastic language with high-precision lexical material such as drug names, abbreviations, dosages, laboratory analytes, or encounter-specific phrases. A purely dense retrieval stack risks blurring distinctions that matter clinically, whereas a purely lexical stack can miss paraphrases and cross-sentence semantic matches. The codebase therefore implements hybrid retrieval rather than choosing one family of retriever exclusively. `QueryEngine.query()` can expand the query, retrieve candidates from both dense and sparse channels, merge them via reciprocal-rank fusion, and optionally rerank them with a cross-encoder before the context bundle is assembled. This design follows classic BM25 and fusion ideas [2,3], but its implementation is concrete and inspectable in the repository. (Code: `backend/app/services/query_engine.py`, `backend/app/services/vector_store.py`, `backend/app/services/bm25_index.py`, `backend/app/services/reranker.py`)

Temporal structure adds a second source of difficulty. Clinical state is not timeless: medications begin and end, diagnoses evolve, and findings that were active in one encounter may no longer be active in another. The repository’s bundled temporal graph JSON demonstrates exactly this kind of date-scoped representation. For example, it includes an open-ended medication exposure for Lisinopril beginning on `2018-07-25`, while other edges such as an acute kidney injury episode are bounded between `2024-02-10` and `2024-02-18`; the graph service then exposes point-in-time filtering through `query_temporal_state()`, which keeps only relationships active on the requested date. This is the reason a clinical graph cannot be treated as a static bag of triples: the same entity may be safe, unsafe, current, or historical depending on the date parameter attached to the query. (Code: `backend/data/temporal_graph.json`, `backend/app/services/graph.py`, `backend/app/models/persistence.py`, `backend/app/api/graph.py`)

This report analyzes the system as implemented rather than as imagined. Section 3 presents the deployed architecture, including ingress, routing, and persistence. Section 4 describes the retrieval pipeline in its actual code path, including one important correction to the task brief: query expansion is implemented in `query_engine.py`, while `rag.py` delegates retrieval-bundle construction to that engine. Section 5 examines the temporal graph and entity normalization layers. Section 6 studies the agent workflow and its adjudication step. Section 7 summarizes the evaluation and quality-gating framework. Sections 8 and 9 then address security/compliance boundaries and the limitations that matter most for research or doctoral applications. (Code: `docker-compose.yml`, `nginx/nginx.conf`, `backend/app/main.py`, `backend/app/services/rag.py`, `backend/app/services/query_engine.py`, `backend/app/services/graph.py`, `backend/app/services/agent.py`, `backend/app/services/evaluation_runner.py`)

---

## 3. System Architecture

### 3.1 High-Level Overview

```text
Browser
  |
  v
nginx reverse proxy
  |
  +--> /              -> static frontend
  |
  +--> /api/*         -> FastAPI application
                          |
                          +--> Chat
                          +--> Agents
                          +--> Images
                          +--> Documents
                          +--> Graph
                          +--> Admin
                          +--> Eval
                                   |
                                   v
                        RAG Service -> Query Engine -> Vector Store + BM25
                                   |
                                   v
                        Temporal Graph Service -> PostgreSQL / optional Neo4j
                                   |
                                   v
                        LLM Service -> Groq (text primary) / Gemini (fallback)
                        Vision Service -> Gemini medical-image analysis
```

The deployment topology shown above is directly represented in the repository. `docker-compose.yml` defines separate `nginx`, `api`, `web`, `postgres`, `redis`, `neo4j`, and worker containers, with nginx listening on port 80 and proxying `/api/` to the FastAPI backend while forwarding `/` to the static frontend container. The backend then mounts multiple routers under the configured API prefix, including `chat`, `documents`, `graph`, `images`, `agents`, `eval`, and `admin`, with additional routes for audio, entity normalization, and stored evaluations. SSE support is handled end-to-end rather than implicitly: the chat API emits `text/event-stream` with `X-Accel-Buffering: no`, and the browser chat component renders streamed updates incrementally. (Code: `docker-compose.yml`, `nginx/nginx.conf`, `backend/app/main.py`, `backend/app/api/chat.py`, `frontend/public/js/components/chat-interface.js`)

From a service-boundary perspective, the system is composed of explicit orchestration layers rather than opaque framework callbacks. `RAGService` is responsible for building retrieval, document, and image bundles and for normalizing answer text and citations. `QueryEngine` owns retrieval-time orchestration. `ClinicalGraphService` owns graph persistence and temporal export/query behavior. `AgentOrchestrator` owns plan execution, synthesis, and verification. `LLMService` and `VisionService` isolate model-provider interactions. This decomposition is important for research exposition because it makes the boundary between retrieval, reasoning, graph access, and answer safety visible in the code. (Code: `backend/app/services/rag.py`, `backend/app/services/query_engine.py`, `backend/app/services/graph.py`, `backend/app/services/agent.py`, `backend/app/services/llm.py`, `backend/app/services/vision.py`)

### 3.2 Data Persistence Layer

| Store | Role in the current implementation |
|---|---|
| PostgreSQL | Primary durable store for user/session data, audit records, persisted chunk text, and graph nodes/edges. `RefreshToken`, `UserSession`, `DocumentChunk`, `GraphNode`, and `GraphEdge` are relational models rather than transient objects. (Code: `backend/app/models/user.py`, `backend/app/core/auth.py`, `backend/app/core/audit.py`, `backend/app/models/persistence.py`, `backend/app/services/graph.py`, `backend/app/services/bm25_index.py`) |
| Redis | Auxiliary infrastructure service for caching, session-store semantics, and pub/sub support, initialized during application startup. The current rate limiter is still in-memory rather than Redis-backed, so Redis should be described as present infrastructure, not yet the authoritative rate-limit store. (Code: `backend/app/core/redis.py`, `backend/app/main.py`, `backend/app/core/rate_limiter.py`) |
| FAISS | Dense vector index persisted locally as `index.faiss` plus `chunks.pkl`. The present code constructs `faiss.IndexFlatIP(dim)` and loads the embedding model from the configurable `embedding_model`; `backend/app/core/config.py` sets `sentence-transformers/all-mpnet-base-v2` and `embedding_dim=768` as defaults, although both can be overridden by environment. (Code: `backend/app/services/vector_store.py`, `backend/app/core/config.py`) |
| Sparse retrieval layer | The sparse side is not a standalone external database. Instead, the repository implements BM25-style retrieval over persisted chunk text, using `rank_bm25.BM25Okapi` in in-memory mode and PostgreSQL full-text search in application mode. This is still a sparse lexical retrieval subsystem, but its persistence is relational rather than a separate inverted-index service. (Code: `backend/app/services/bm25_index.py`, `backend/app/models/persistence.py`) |

This persistence design reflects a demo/research trade-off. It keeps the full stack runnable from Compose, avoids mandatory third-party vector infrastructure, and preserves inspectability, but it also means that scaling boundaries are visible early, especially on the vector side where `IndexFlatIP` remains an exact scan index. (Code: `docker-compose.yml`, `backend/app/services/vector_store.py`, `backend/app/core/config.py`)

---

## 4. Retrieval Pipeline

### 4.1 Document Processing

Document ingestion is implemented as a deliberate preprocessing pipeline rather than as retrieval-time ad hoc parsing. `document_processing.py` builds chunk records using a configured chunk size of 512 words and an overlap of 64 words, preserves page and source-offset metadata when available, assigns an embedding version, writes chunks into the dense and sparse stores, and forwards extracted entities into the temporal graph and normalization services. This means retrieval operates over chunked and indexed artifacts rather than raw uploaded files. The chunking strategy is also consistent across dense and sparse indexing because the same chunk records are reused downstream. (Code: `backend/app/services/document_processing.py`, `backend/app/core/config.py`, `backend/app/services/vector_store.py`, `backend/app/services/bm25_index.py`, `backend/app/services/graph.py`, `backend/app/services/entity_normalization.py`)

At the dense layer, embeddings are produced by `SentenceTransformer(settings.embedding_model)` and inserted into a FAISS index that persists locally on disk. At the sparse layer, the corresponding chunk text and normalized tokens are persisted as `DocumentChunk` rows. The consequence is a dual-index architecture: dense retrieval is optimized for semantic similarity, while sparse retrieval preserves exact lexical recall over the same chunk boundaries. (Code: `backend/app/services/vector_store.py`, `backend/app/services/document_processing.py`, `backend/app/services/bm25_index.py`, `backend/app/models/persistence.py`)

### 4.2 Query-Time Pipeline

The current implementation realizes a five-stage query-time pipeline.

1. **Query Expansion.** The task brief associates query expansion with `rag.py`, but the code places it in `QueryEngine._expand_query()`. `RAGService.build_retrieval_bundle()` delegates to `QueryEngine.query()`, which optionally asks the LLM for two alternative phrasings and appends them to the original query. This stage is configuration-controlled through `use_query_expansion`. (Code: `backend/app/services/rag.py`, `backend/app/services/query_engine.py`, `backend/app/core/config.py`)

2. **Dense Retrieval.** For each query variant, the engine calls `vector_store_service.search()` with `fetch_k = top_k * 3`; the default `top_k` is five. The FAISS backend uses normalized sentence-transformer embeddings and `IndexFlatIP`, so the ranking behaves as cosine-style similarity over normalized vectors even though the index primitive is inner product. Candidate metadata includes document identifiers, page bounds, and source offsets for later citation generation. (Code: `backend/app/services/query_engine.py`, `backend/app/services/vector_store.py`, `backend/app/core/config.py`)

3. **Sparse Retrieval.** When hybrid search is enabled, the engine also calls `bm25_index.search()` for each query variant. In-memory mode uses `rank_bm25.BM25Okapi` when installed; application mode uses PostgreSQL full-text search over normalized chunk text, with a fallback lexical overlap scorer for non-PostgreSQL environments. This stage is especially important for abbreviations, analytes, drug names, and exact phrase matches that dense embeddings may smooth away. (Code: `backend/app/services/query_engine.py`, `backend/app/services/bm25_index.py`)

4. **Reciprocal-Rank Fusion.** The engine deduplicates candidates across query variants and retrieval channels, then computes an RRF score in `_rrf_merge()` using the best observed dense and sparse ranks. The implemented scoring rule is

   \[
   \mathrm{RRF}(d) = \sum_{r \in \{\mathrm{vector}, \mathrm{bm25}\}} \frac{1}{k + \mathrm{rank}_r(d)},
   \quad k = 60.
   \]

   This matches the classical fusion intuition of rewarding documents that consistently appear near the top of multiple lists without requiring score calibration across retrievers. (Code: `backend/app/services/query_engine.py`)

5. **Cross-Encoder Reranking.** If reranking is enabled, the fused candidate set is passed to `reranker_service.rerank()`, which loads the configured cross-encoder model and rescored pairs down to the final top-k list. The configured default reranker is `cross-encoder/ms-marco-MiniLM-L-6-v2`. The query engine degrades gracefully if reranking fails, returning fusion scores instead of aborting the request. (Code: `backend/app/services/query_engine.py`, `backend/app/services/reranker.py`, `backend/app/core/config.py`)

Two implementation details are worth noting for research interpretation. First, the retrieval pipeline is robust to partial failure: query expansion and reranking are both surrounded by fallback paths. Second, the sparse component is not merely a reranking hint; it participates as a first-class retrieval channel before fusion. This matters for clinical retrieval because lexical specificity and semantic generalization are both necessary, and the code realizes that claim structurally rather than rhetorically. (Code: `backend/app/services/query_engine.py`, `backend/app/services/bm25_index.py`, `backend/app/services/reranker.py`)

### 4.3 Context Assembly

Retrieval results do not flow directly into the model prompt. `RAGService` converts retrieved items into `ContextItem` structures, assigns citation identifiers such as `SRC1` and fact-level graph IDs such as `GRAPH-COND-001`, bounds the amount of text included through `_build_context_text()`, and ensures that the final answer can be normalized back into a citation-bearing response with a heuristic evidence-support score. This value is not calibrated clinical confidence. The service parses the terminal evidence-support marker, strips it from user-visible prose, and appends a clinician-review disclaimer to demo answers. In other words, answer generation is coupled to a context policy, not just to the raw retriever output. (Code: `backend/app/services/rag.py`, `backend/app/core/config.py`)

---

## 5. Temporal Knowledge Graph

### 5.1 Ontology

The graph layer is not an informal JSON store but a typed ontology encoded in `FORMAL_GRAPH_SCHEMA`. The current schema defines nine node labels: `Patient`, `Encounter`, `Document`, `Condition`, `Symptom`, `Medication`, `Lab`, `ImagingStudy`, and `Finding`. It also defines six relationship types: `HAS_CONDITION`, `TOOK_MEDICATION`, `HAS_FINDING`, `MENTIONED_IN`, `OCCURRED_AT`, and `RELATED_TO`. This ontology is enforced at the service layer when graph substructures are built from documents and images. (Code: `backend/app/services/graph.py`)

### 5.2 Temporal Edges

Temporal behavior is encoded directly in the persistence model. `GraphEdge` includes `start_date` and `end_date`, and `ClinicalGraphService.query_temporal_state()` filters edges through `_is_active_on_date()` before returning results. The bundled temporal JSON illustrates why this matters. One edge records a Lisinopril-related relationship beginning on `2018-07-25` with no end date, whereas another edge records an acute kidney injury interval beginning on `2024-02-10` and ending on `2024-02-18`. These are not interchangeable facts: one is ongoing medication exposure, the other is a bounded adverse clinical state. A point-in-time query such as “What relationships were active on 2024-02-12?” therefore requires date filtering rather than simple node matching. (Code: `backend/app/models/persistence.py`, `backend/app/services/graph.py`, `backend/data/temporal_graph.json`, `backend/app/api/graph.py`)

The graph service is database-backed by default and can optionally mirror or query through Neo4j when `use_neo4j` is enabled. Even in that optional configuration, the primary persistence path remains relational, and Neo4j is treated as an auxiliary graph-native execution surface rather than the only source of truth. The repository further threads `tenant_id` and `patient_id` through graph persistence and query helpers, which is best read as scoped graph access rather than fully realized organization-level multi-tenancy. (Code: `backend/app/services/graph.py`, `backend/app/core/config.py`, `backend/app/api/graph.py`, `backend/app/services/neo4j_graph.py`)

### 5.3 Entity Normalization

The entity normalization service combines deterministic mapping and optional biomedical NLP. Its module docstring states that it maps entities into UMLS, SNOMED CT, RxNorm, and ICD-10; the implementation includes a curated canonical concept table, an optional lazily loaded SciSpaCy pipeline gated by configuration, and an LLM-backed fallback path for unmatched entities. This is a pragmatic design choice for a portfolio/research system: deterministic mappings support reproducibility, while the optional NLP path broadens coverage without making SciSpaCy a hard runtime dependency. (Code: `backend/app/services/entity_normalization.py`, `backend/app/core/config.py`)

Because normalization is invoked during document processing and is available as a tool registry function, the graph is not merely storing raw strings from notes. Instead, it is positioned to store clinically meaningful canonical forms, even if the normalization quality remains bounded by the curated knowledge base and optional model availability in the local environment. (Code: `backend/app/services/document_processing.py`, `backend/app/services/entity_normalization.py`, `backend/app/services/tool_registry.py`)

---

## 6. Agentic Workflow with Safety Adjudicator

### 6.1 Plan→Execute→Reflect Loop

The user brief describes a Plan→Execute→Reflect loop, but the current code is more precisely a Plan→Execute→Synthesize→Verify workflow implemented as a LangGraph `StateGraph`. `AgentOrchestrator` registers `plan_node`, `execute_step_node`, `synthesize_node`, and `verify_node`, routes execution conditionally until all plan steps complete, and then conditionally routes failed verification events back into synthesis for at most one additional repair cycle before termination. This design keeps the reflective behavior explicit: the system does not free-form “think again,” but instead revises synthesis in response to specific verification flags collected from the adjudicator. (Code: `backend/app/services/agent.py`)

### 6.2 Tool Registry

The repository’s clinical tool surface is larger than the eight-item list in the task prompt. `tool_registry.py` currently registers concrete tools for `search_documents`, `query_clinical_graph`, `medical_calculator`, `pubmed_search`, `drug_interaction`, `analyze_image`, `search_graph`, `clinical_eval`, and `normalize_entities`. In addition, `agent.py` registers three internal delegation tools that route work toward specialized sub-agent roles. This distinction matters because the externally meaningful clinical interface lives mostly in `tool_registry.py`, while `agent.py` adds orchestration-specific internal routing constructs. (Code: `backend/app/services/tool_registry.py`, `backend/app/services/agent.py`)

From a clinical reasoning perspective, the tool composition is intentionally heterogeneous. The agent can search retrieved text, consult temporal graph state, compute structured medical calculations, normalize terms, analyze medical images, and invoke a red-team evaluator over its own draft. This makes the workflow less like a single LLM call and more like a bounded tool-using pipeline with evidence checkpoints. (Code: `backend/app/services/tool_registry.py`, `backend/app/services/agent.py`)

### 6.3 Safety Adjudicator

The adjudication mechanism is explicit in the code path. `verify_node()` builds a source-context bundle from accumulated tool results and passes the draft synthesis into `clinical_eval`. That tool prompts the model as a “Clinical Adjudicator (Red Team)” and instructs it to reject hallucinations, contradictions, or potentially dangerous advice. The return payload is structured as JSON with `status`, `confidence_score`, and `flags`. If the adjudicator returns an error or produces unparsable output, the system defaults to rejection. If the draft is rejected, `_build_rejected_answer()` produces an explicit refusal that surfaces the failure reasons rather than silently falling back to the unsafe draft. (Code: `backend/app/services/agent.py`, `backend/app/services/tool_registry.py`, `backend/app/services/llm.py`)

This design is useful for research discussion because it externalizes a safety review stage. At the same time, it should not be overstated: the adjudicator uses the same `LLMService` abstraction as the generator, so any conclusions about robustness must account for judge-model bias and shared-provider failure modes. (Code: `backend/app/services/agent.py`, `backend/app/services/tool_registry.py`, `backend/app/services/llm.py`)

---

## 7. Evaluation Framework

### 7.1 Internal Quality Suite

The repository contains an internal evaluation runner whose default baseline dictionary defines seven release-gating metrics: `answer_groundedness >= 0.85`, `citation_correctness >= 0.85`, `retrieval_precision >= 0.75`, `retrieval_recall_proxy >= 0.85`, `clinician_acceptance_rate >= 0.80`, `hallucination_rate <= 0.15`, and `overall_score >= 0.82`. The suite is versioned as `2026-03-26`, aggregates case-level scores, applies threshold logic with a tolerance margin, and stores structured results through the evaluation storage service. These baselines make the project analytically stronger than a demo that reports only example outputs. (Code: `backend/app/services/evaluation_runner.py`)

The runner also computes additional metrics beyond the seven baselines, including `faithfulness`, `answer_relevancy`, `context_recall`, and `context_precision`, then aliases some of them into dashboard-facing names such as `citation_accuracy` and `relevance`. This indicates that the code distinguishes between release gates and richer diagnostic telemetry. (Code: `backend/app/services/evaluation_runner.py`)

### 7.2 RAGAS Integration

The external-style RAG evaluation path is implemented separately in `backend/scripts/evaluate_ragas.py`. That script loads the bundled golden dataset and evaluates three RAGAS metrics: `faithfulness`, `answer_relevancy`, and `context_precision`. The dataset currently contains five clinical question-answer pairs, which is useful for smoke testing but insufficient for statistically meaningful comparative claims. In clinical settings, this matters because faithfulness is the closest available automated proxy for hallucination risk [4], yet a five-case benchmark can only indicate viability, not reliability under deployment conditions. (Code: `backend/scripts/evaluate_ragas.py`, `backend/data/golden_evaluation_dataset.jsonl`)

### 7.3 Phase-gated Quality Gates

Quality control is also encoded at the shell-script level. `scripts/quality/phase_check.sh` implements phase-specific checks for phases 1 through 8, while security-oriented checks that function as a phase-0 gate are split across `scripts/quality/security_gate.sh` and `scripts/check-secrets.sh`. This is worth stating precisely because a casual summary could imply that all phases, including security, are implemented in one script. The repository instead separates product-phase gates from security-specific enforcement. (Code: `scripts/quality/phase_check.sh`, `scripts/quality/security_gate.sh`, `scripts/check-secrets.sh`)

---

## 8. Security and Compliance Architecture

The repository implements a non-trivial set of security primitives. Authentication combines JWT access tokens with opaque refresh tokens, stores refresh-token hashes rather than raw tokens, and binds active sessions through `current_access_jti` and `current_refresh_token_id` to reduce replay risk. Authorization is role-based, with four explicit roles: `viewer`, `nurse`, `physician`, and `admin`. These mechanisms are application-level controls rather than mere README claims. (Code: `backend/app/core/auth.py`, `backend/app/models/user.py`)

Request observability is paired with accountability controls. `AuditLogMiddleware` persists one audit record per API request under `/api/`, and `RateLimitMiddleware` enforces a token-bucket limit per client IP. Privacy support goes beyond login controls: `privacy.py` exposes data export and purge helpers and explicitly tombstones vector-store and BM25 artifacts when user-owned data are purged. Medical-image handling also includes DICOM PHI scrubbing before ingestion when DICOM uploads are allowed by policy. Finally, the answer path itself enforces a safety disclaimer when grounded evidence is insufficient or the response confidence is low, and the same disclaimer is exposed via a health endpoint for frontend consumption. (Code: `backend/app/core/audit.py`, `backend/app/core/rate_limiter.py`, `backend/app/services/privacy.py`, `backend/app/services/dicom_scrubber.py`, `backend/app/services/image_processing.py`, `backend/app/services/rag.py`, `backend/app/api/health.py`, `backend/app/core/config.py`)

These controls are relevant, but they do not make the system HIPAA-compliant. The codebase provides authentication, authorization, audit logging, DICOM metadata scrubbing support, and privacy operations, yet it does not encode the full organizational, contractual, infrastructure, and operational controls required for regulated clinical deployment. Clinical deployment would require additional controls around key management, formal incident handling, deployment hardening, access governance, and validated operating procedures. (Code: `backend/app/core/auth.py`, `backend/app/core/audit.py`, `backend/app/services/dicom_scrubber.py`, `backend/app/services/privacy.py`, `SECURITY.md`)

---

## 9. Limitations and Future Work

The system is technically substantial, but its limitations are equally important for an honest research presentation.

1. The bundled golden evaluation dataset is small (`n=5`), so benchmark variance and confidence intervals are not meaningfully estimable from the repository alone. The current RAGAS script is therefore best interpreted as a regression harness, not a definitive study. (Code: `backend/data/golden_evaluation_dataset.jsonl`, `backend/scripts/evaluate_ragas.py`)
2. The distributed data assets are demo-oriented rather than real hospital data. The seed script explicitly bootstraps “demo credentials” from the golden dataset, and the repository’s sample clinical documents are handcrafted examples. This is appropriate for a portfolio project, but it limits claims about robustness on authentic EHR distributions. (Code: `scripts/demo/seed_demo_data.py`, `backend/data/golden_evaluation_dataset.jsonl`, `examples/sample_docs/discharge_summary.txt`)
3. The default dense index is local FAISS with `IndexFlatIP`, which keeps the stack reproducible but does not provide horizontal scale. The code supports Qdrant as an alternative backend, yet the default deployment remains single-node vector storage. (Code: `backend/app/services/vector_store.py`, `backend/app/core/config.py`)
4. The clinical adjudicator evaluates outputs through the same `LLMService` abstraction used for generation, which introduces judge-model bias and correlated provider failure modes. A rejected answer is safer than an unchecked one, but it is still being judged by a related model path. (Code: `backend/app/services/tool_registry.py`, `backend/app/services/agent.py`, `backend/app/services/llm.py`)
5. The multimedia path supports DICOM upload, sanitization, analysis, and a browser detail panel, but the frontend does not implement a dedicated diagnostic DICOM viewer stack with radiology-grade interaction semantics. The current UI centers on upload, analysis overlays, and findings display rather than full workstation-style viewing. (Code: `backend/app/services/image_processing.py`, `backend/app/api/images.py`, `frontend/public/js/components/medical-images.js`)
6. The frontend intentionally uses static HTML/CSS and vanilla JavaScript web components with no build step. This keeps deployment simple and inspectable, but it also constrains typed component reuse and ecosystem integration relative to a larger front-end framework. (Code: `frontend/README.md`, `frontend/public/js/components/chat-interface.js`, `frontend/public/js/components/medical-images.js`)
7. The repository contains automated evaluation and release gates, but it does not contain artefacts for a prospective clinician validation study. Any claim about clinical usefulness should therefore be limited to engineering plausibility rather than human-subject evidence. (Code: `backend/app/services/evaluation_runner.py`, `backend/scripts/evaluate_ragas.py`, `scripts/quality/phase_check.sh`)

Future work follows naturally from the current architecture.

1. Extend the ingestion path from uploaded documents and seeded graph facts toward HL7 FHIR R4 bundles so that the existing document-processing and graph-persistence services can consume structured encounter payloads rather than only free-text uploads and demo seeds. (Code: `backend/app/services/document_processing.py`, `backend/app/services/graph.py`, `scripts/demo/seed_demo_data.py`)
2. Standardize more orchestration paths on the existing LangGraph substrate. The agent workflow already uses LangGraph, but chat and retrieval orchestration remain separate services; a fuller unification could reduce duplicated orchestration logic and make safety policies more uniform. (Code: `backend/app/services/agent.py`, `backend/app/services/chat_orchestrator.py`, `backend/app/services/rag.py`)
3. Generalize the existing user/tenant scoping present in graph persistence and API filters into explicit organization-level multi-tenancy across the full application surface, including retrieval, storage, and admin tooling. (Code: `backend/app/services/graph.py`, `backend/app/api/graph.py`, `backend/app/services/tool_registry.py`, `SECURITY.md`)
4. Replace purely automated quality evidence with prospective expert evaluation. The current internal suite and RAGAS script provide useful regression signals, but the next research-grade step would be a clinician-reviewed study that audits usefulness, citation quality, and safety under realistic workflows. (Code: `backend/app/services/evaluation_runner.py`, `backend/scripts/evaluate_ragas.py`)

---

## 10. References

[1] Lewis, P., Perez, E., Piktus, A., et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *NeurIPS*.

[2] Robertson, S., & Zaragoza, H. (2009). The Probabilistic Relevance Framework: BM25 and Beyond.

[3] Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009). Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods.

[4] Es, S., James, J., Espinosa Anke, L., & Schockaert, S. (2023). RAGAS: Automated Evaluation of Retrieval Augmented Generation.

[5] Neumann, M., King, D., Beltagy, I., & Ammar, W. (2019). ScispaCy: Fast and Robust Models for Biomedical NLP.
