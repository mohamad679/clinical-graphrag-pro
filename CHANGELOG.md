# Changelog

All notable changes to Clinical GraphRAG Pro are documented here.  
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)  
Versioning: [Semantic Versioning](https://semver.org/)

---

## [Unreleased]
### Planned
- No additional unreleased roadmap items are explicitly documented in the current repository.

---

## [1.0.0] — 2026-03-17

### Summary
Production-hardened release completing the documented 8/8 remediation phases
with persistent authentication, multimedia ingestion, observability,
evaluation gating, and release-readiness tooling.

### Added
- **Phase 8: Final Hardening and Release Readiness**
  - Staging smoke test script (`backend/scripts/staging_smoke.py`)
  - Release-readiness orchestration (`scripts/quality/release_readiness.sh`)
  - Release handoff and readiness docs (`docs/release-handoff.md`, `docs/release-readiness.md`)
  - Backup and restore operations scripts (`scripts/ops/*.sh`)

- **Phase 7: Documentation and Architecture Alignment**
  - API reference (`docs/API.md`) synchronized to the current implementation
  - Architecture document (`docs/ARCHITECTURE.md`)
  - Docs alignment regression test (`backend/tests/test_phase7_docs_alignment.py`)
  - Updated repository/runtime docs (`README.md`, `CONTRIBUTING.md`, `frontend/README.md`, `docs/walkthrough.md`, `docs/implementation_plan.md`)

- **Phase 6: Test and Quality Gates**
  - Internal quality-suite runner (`backend/app/services/evaluation_runner.py`)
  - Persistent evaluation storage and baseline workflow (`backend/app/services/evaluation_storage.py`, `backend/app/api/evaluations.py`)
  - Stable backend gate (`scripts/quality/backend_gate.sh`)
  - GitHub Actions quality workflow (`.github/workflows/backend-quality.yml`)

- **Phase 5: Build, Runtime, and Environment Reliability**
  - Durable background job state with retry/backoff handling (`backend/app/services/job_state.py`, `backend/app/worker.py`)
  - Fine-tuning orchestration with LoRA-oriented job configuration (`backend/app/services/fine_tune.py`)
  - Model registry (`backend/app/services/model_registry.py`)
  - Dataset management services and APIs (`backend/app/services/datasets.py`, `backend/app/api/fine_tune.py`)
  - Expanded migration set for auth, runtime state, document pipeline, workflow hardening, and multimedia (`backend/alembic/versions/20260326_0003_persistent_auth.py` through `backend/alembic/versions/20260326_0008_multimedia_pipeline_hardening.py`)

- **Phase 4: Retrieval, Observability, and Multimedia**
  - BM25 lifecycle integration and hybrid retrieval stabilization (`backend/app/services/bm25_index.py`, `backend/app/services/query_engine.py`)
  - Prometheus metrics and request-scoped observability (`backend/app/core/metrics.py`, `backend/app/core/observability.py`)
  - Medical image upload, async analysis, and annotation pipeline (`backend/app/api/images.py`, `backend/app/services/image_processing.py`)
  - Gemini-backed vision integration (`backend/app/services/vision.py`)
  - Groq-backed audio transcription pipeline (`backend/app/services/audio_processing.py`)
  - DICOM scrubbing and guarded `.dcm` handling (`backend/app/services/dicom_scrubber.py`)

- **Phase 3: Correctness and Agent Safety**
  - Agent verification / adjudication flow with persisted workflow history (`backend/app/services/agent.py`, `backend/app/services/tool_registry.py`)
  - Drug interaction lookup via RxNav (`backend/app/services/tool_registry.py`)
  - Clinical calculator tools for BMI, eGFR, and CHA2DS2-VASc (`backend/app/services/tool_registry.py`)
  - Correctness and support regression suites (`backend/tests/test_phase3_correctness.py`, `backend/tests/test_phase3_support_endpoints.py`)

- **Phase 2: Security Hardening and Advanced Retrieval/Agent Tooling**
  - Hybrid retrieval stack using FAISS, BM25, reciprocal-rank fusion, and reranking (`backend/app/services/vector_store.py`, `backend/app/services/bm25_index.py`, `backend/app/services/reranker.py`, `backend/app/services/query_engine.py`)
  - LangGraph-based agent orchestrator and SSE workflow endpoint (`backend/app/services/agent.py`, `backend/app/api/agents.py`)
  - Tool registry with nine registered tools (`backend/app/services/tool_registry.py`)
  - Temporal graph querying and visualization endpoints (`backend/app/services/graph.py`, `backend/app/api/graph.py`)

- **Phase 1: Backend Foundation**
  - FastAPI application with lifespan management and health endpoints (`backend/app/main.py`, `backend/app/api/health.py`)
  - SQLAlchemy async data layer with Alembic migrations (8 versions under `backend/alembic/versions/`)
  - JWT access tokens, opaque refresh tokens, and DB-backed session state (`backend/app/core/auth.py`, `backend/app/models/user.py`)
  - RBAC across viewer, nurse, physician, and admin roles
  - Audit logging, rate limiting, privacy export/purge, and admin session controls (`backend/app/core/audit.py`, `backend/app/core/rate_limiter.py`, `backend/app/services/privacy.py`)
  - Document processing, evaluation, and entity normalization services (`backend/app/services/document_processing.py`, `backend/app/services/evaluation.py`, `backend/app/services/entity_normalization.py`)

- **Phase 0: Security and Configuration Baseline**
  - Secrets gate (`scripts/check-secrets.sh`) and security quality gate (`scripts/quality/security_gate.sh`)
  - Security-focused regression suite (`backend/tests/test_phase0_security.py`)
  - Hardened environment templates (`.env.example`, `backend/.env.example`)
  - JWT secret length enforcement and CORS credential conflict detection (`backend/app/core/config.py`, `backend/app/main.py`)

### Infrastructure
- Docker Compose variants for development, staging, and production (`docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.staging.yml`, `docker-compose.prod.yml`)
- Backend Docker images including a Hugging Face variant (`backend/Dockerfile`, `backend/Dockerfile.hf`)
- nginx reverse proxy plus SSE-friendly chat response headers (`nginx/nginx.conf`, `backend/app/api/chat.py`)
- Makefile targets for `dev`, `test`, and `lint` (`Makefile`)

### Frontend
- Static nginx-served frontend using HTML, CSS, and vanilla JavaScript (`frontend/README.md`, `frontend/public/index.html`)
- Component modules for chat, documents, images, evaluations, agent workflows, auth, and graph views (`frontend/public/js/components/*.js`)
- SSE chat rendering in the browser (`frontend/public/js/components/chat-interface.js`)
- D3-based force-directed knowledge graph visualization (`frontend/public/js/components/knowledge-graph.js`, `frontend/public/js/lib-loader.js`)
- Chart.js evaluation charts (`frontend/public/js/components/evaluations-dashboard.js`)

---

## [0.1.0] — 2026-02-19

### Added
- Initial repository scaffold from the first recorded project commit on 2026-02-19
- FastAPI backend, nginx reverse proxy, Docker Compose stack, and backend/frontend Dockerfiles
- Core API modules for chat, documents, images, agents, evaluation, graph, admin, and health
- Backend service modules for retrieval, agents, evaluation, fine-tuning, reranking, vector storage, and vision
- Project docs, Makefile, tests, and MIT License
