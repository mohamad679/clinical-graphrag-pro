---
title: Clinical GraphRAG Pro
emoji: 🏥
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Clinical GraphRAG Pro

> **What this is:** A senior engineer portfolio project 
> demonstrating production-grade AI system design: hybrid RAG 
> (FAISS + BM25 + RRF), temporal clinical knowledge graph, 
> LangGraph agent orchestration, citation-grounded answer 
> generation, multi-tenant access isolation, JWT/RBAC auth, 
> Prometheus observability, and Docker deployment. 
> 
> **What this is not:** A trained model, a clinically validated 
> system, a platform compliant with HIPAA, or a production medical 
> device. All evaluation datasets are synthetic smoke tests.

Clinical GraphRAG Pro is a clinical AI systems portfolio project. It demonstrates a production-inspired architecture for retrieval-augmented clinical question answering: FastAPI, PostgreSQL, Redis/Celery, hybrid FAISS plus sparse retrieval, optional reranking, a temporal graph layer, safe-buffered SSE streaming, authentication, audit logging, and a static Web Components frontend. Local benchmark sparse retrieval uses `rank_bm25.BM25Okapi`; PostgreSQL runtime sparse retrieval uses Full-Text Search with `ts_rank_cd`, not BM25.

This project is for educational and portfolio demonstration purposes only. It is not a medical device, not clinically validated, and must not be used for diagnosis, treatment, triage, medication decisions, or real patient care. All outputs require review by qualified clinical professionals.

<!-- MedQA evaluation requires live LLM credentials. 
     See BENCHMARKS.md for the retrieval metrics that were measured. -->
![MedQA Accuracy](https://img.shields.io/badge/MedQA%20Accuracy-N%2FA-lightgrey)
![RAG Improvement](https://img.shields.io/badge/RAG%20Improvement-N%2FA-lightgrey)
![Response Latency](https://img.shields.io/badge/Response%20Latency-14.7ms%20retrieval-blue)
![Verification](https://img.shields.io/badge/Verification-local%20gate-orange)

## What This Is

- A senior-engineer portfolio repository for clinical AI architecture, retrieval, orchestration, and evaluation patterns.
- A reproducible demo stack with local Docker services, environment templates, tests, and benchmark scripts.
- An inspectable implementation of hybrid retrieval, temporal graph querying, workflow orchestration, and grounded safe-buffered SSE streaming.

## What This Is Not

- Not a medical device.
- Not clinically validated.
- Not HIPAA-certified or compliant with HIPAA as shipped.
- Not safe for diagnosis, treatment, triage, medication decisions, or real patient care.
- Not connected to real EHR systems or validated on real patient workflows.

## Architecture Summary

> This is a portfolio/research system demonstrating AI systems 
> engineering patterns. It is not a trained model, not clinically 
> validated, and not production-deployed.

```text
Browser Web Components
        |
        v
      nginx
        |
        v
     FastAPI
        |
        +--> PostgreSQL auth, sessions, audit logs, graph state
        +--> Redis/Celery background jobs
        +--> FAISS dense retrieval + BM25 sparse retrieval
        +--> Query expansion, RRF fusion, optional reranking
        +--> LLM provider abstraction
        +--> SSE chat streaming and workflow traces
```

Full details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Capability Matrix

| Capability | Status | Notes |
| --- | --- | --- |
| Dense retrieval with FAISS | Implemented | Local and demo path. |
| Local BM25Okapi | Implemented | Benchmark/in-memory sparse path via `rank_bm25.BM25Okapi`. |
| PostgreSQL Full-Text Search | Implemented | Database-backed sparse runtime via generated `search_vector` and `ts_rank_cd`; not BM25. |
| Hybrid rank fusion | Implemented | RRF combines dense and sparse candidates; quality improvement must be demonstrated by benchmark. |
| Cross-encoder reranker | Implemented | Applied/model-loaded/fallback status is reported in trace diagnostics. |
| Temporal graph persistence | Implemented | PostgreSQL is the source of truth. |
| Neo4j mirror | Optional | Secondary mirror only; not authoritative. |
| Qdrant | Optional/staging | Available vector backend when configured; FAISS remains local default. |
| Redis distributed cache | Implemented | Redis mode uses async Redis with JSON values and TTL. Development/offline Redis outages fall back to in-memory; production bypasses cache. |
| LoRA fine-tuning | Scaffold only | No trained clinical model is claimed. |
| Safe-buffered SSE streaming | Implemented | The system validates grounding/abstention before emitting answer chunks to the client. Provider-level streaming utilities may exist, but the chat path intentionally uses safe-buffered streaming to avoid sending unvalidated answer tokens. |
| Clinical validation | Not performed | Synthetic regression tests are not clinical validation. |
| HIPAA compliance | Not claimed | Security controls are engineering safeguards, not a compliance program. |
| Medical-device readiness | Not claimed | Not for diagnosis, treatment, triage, or medication decisions. |
| Real EHR integration | Not implemented | FHIR/sample ingestion is synthetic/demo oriented unless separately configured. |

TLS boundary: the local Docker demo uses HTTP. Production must terminate HTTPS at a load balancer or hardened reverse proxy. Do not claim internal HTTPS for the included local Nginx configuration unless that deployment has been changed and verified.

Current truthfulness and verification status:
- [Model Card](MODEL_CARD.md)
- [Threat Model](THREAT_MODEL.md)
- [Evaluation Status](EVALUATION_STATUS.md)
- [Hardening Verification Report](docs/HARDENING_VERIFICATION_REPORT.md)
- [Fine-Tuning Status](docs/FINE_TUNING.md)

For interactive visual overviews, view the **[Architecture Diagrams](docs/diagrams/)**:
- [System Architecture Flow](docs/diagrams/system_architecture.mmd)
- [RAG Retrieval Pipeline](docs/diagrams/rag_pipeline.mmd)
- [Agent LangGraph State Workflow](docs/diagrams/agent_workflow.mmd)
- [Clinical Graph Ontology Model](docs/diagrams/clinical_graph.mmd)
- [Retrieval & Generation Evaluation Pipeline](docs/diagrams/evaluation_pipeline.mmd)

For advanced features and developer configuration:
- [Live & Offline Demo Guide](docs/LIVE_DEMO.md)
- [API Load Testing](docs/LOAD_TESTING.md)
- [Cost Estimation and Pricing](docs/COST_ESTIMATION.md)
- [Local LLM Integration](docs/LOCAL_LLM.md)
- [Model Quantization Options](docs/QUANTIZATION.md)
- [Secure Multi-Tenant Caching](docs/CACHING.md)
- [Synthetic Clinical Data Generator](docs/SYNTHETIC_DATA.md)
- [Observability System Details](docs/OBSERVABILITY.md)
- [Multi-Horizon Product Roadmap](ROADMAP.md)
- [Compilation Status Report](reports/clinical_graphrag_report.md) (generated via `make report`)


## Quickstart From Fresh Clone

```bash
git clone https://github.com/mohamad679/clinical-graphrag-pro
cd clinical-graphrag-pro
cp .env.example .env
cp backend/.env.example backend/.env
make install
make test
```

For the local Docker stack:

```bash
cp .env.example backend/.env
# Replace JWT_SECRET and add GROQ_API_KEY or GOOGLE_API_KEY if you want live LLM calls.
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Then open `http://localhost:3000`. The API is available at `http://localhost:8000/api` in development mode and through nginx at `http://localhost/api` when using the full stack.

## Environment Setup

Do not commit `.env` or `backend/.env`. These files are untracked and excluded from source control. Use [.env.example](.env.example) and [backend/.env.example](backend/.env.example) as templates only, copying them to `.env` and `backend/.env` for local runtime execution.

If a real key is ever shared through a ZIP or external tool, rotate it immediately even if it was never committed to Git.

Required for normal non-debug backend startup:

- `JWT_SECRET`: at least 32 characters; generate with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
- `DATABASE_URL`: async SQLAlchemy URL.
- `REDIS_URL`: Redis URL for cache and background jobs.
- `CORS_ORIGINS`: comma-separated trusted frontend origins.
- `GROQ_API_KEY` or `GOOGLE_API_KEY`: required only for live LLM-backed generation.

Production mode (`APP_ENV=production`) fails fast for known unsafe defaults, including wildcard CORS, missing JWT secret, development database credentials, unauthenticated default Redis URL, and default Neo4j passwords.

## Hugging Face Space Deployment

The Docker Space package serves both the FastAPI backend and the static frontend UI from one container. Do not put Gemini or Hugging Face tokens in source files. After the Space is created, configure provider credentials in the Hugging Face UI under **Settings -> Secrets and variables**:

- `GOOGLE_API_KEY`: Gemini key used by text chat and image analysis.
- `GEMINI_API_KEY`: optional alias; set it to the same value for compatibility.
- `GROQ_API_KEY`: optional text-generation provider key.
- `LLM_PROVIDER`: set as a variable, not a secret, when you want to force a provider such as `gemini`.

After changing Space secrets, restart or rebuild the Space from the Hugging Face **Settings** tab. You can also configure the Gemini key from local `backend/.env` with:

```bash
export HF_TOKEN="<rotated-hugging-face-write-token>"
backend/.venv/bin/python scripts/configure_hf_space_vision.py --repo-id mohi679/clinical-graphrag-pro
```

Deploy with a locally configured Hugging Face write token:

```bash
export HF_TOKEN="<rotated-hugging-face-write-token>"
backend/.venv/bin/python scripts/deploy_hf_space.py --repo-id mohi679/clinical-graphrag-pro
```

## Common Commands

```bash
make install           # create backend/.venv and install backend dependencies
make test              # run backend tests
make coverage          # run backend tests with coverage
make lint              # run configured backend lint checks
make dev               # run local development stack
make demo-offline      # run end-to-end demo offline in retrieval-only mode
make demo-live-google  # run end-to-end demo using Google Gemini
make demo-live-ollama  # run end-to-end demo using local Ollama model
make llm-health        # check status of configured LLM provider
make clean             # remove containers, caches, and generated reports
make verify-final      # run full local verification gate, evaluations, and demo dry-run
```

## Benchmark and Evaluation Status

Current committed benchmark artifacts are in [results/BENCHMARK.md](results/BENCHMARK.md) and [results/benchmark_2026.json](results/benchmark_2026.json). The latest committed run dated `2026-04-02` completed a small retrieval benchmark and did not complete the synthetic MedQA-style generation benchmark because provider credentials were rejected.

Canonical portfolio benchmark report: `results/portfolio_gate_retrieval_benchmark_20260607T163206Z.md`. On synthetic benchmark v2, hybrid RRF improves over dense and sparse retrieval. Optional reranking improves retrieval quality further but materially increases latency, so reranking remains disabled by default on latency-sensitive paths (`USE_RERANKING=false`). These results are synthetic regression results, not clinical validation. Older June 5 and early June 7 retrieval artifacts are retained as historical baselines. See [EVALUATION_STATUS.md](EVALUATION_STATUS.md) for the current table of evaluated modes and non-claims.

| Metric | Result | Evidence |
| --- | ---: | --- |
| MedQA-style direct LLM accuracy | N/A | Provider authentication failed; no score is claimed |
| MedQA-style RAG accuracy | N/A | Provider authentication failed; no score is claimed |
| Retrieval keyword hit rate, FAISS | 100.0% | `n=20` internal retrieval pairs |
| Retrieval keyword hit rate, BM25 | 100.0% | `n=20` internal retrieval pairs |
| Retrieval keyword hit rate, Hybrid + RRF | 100.0% | `n=20` internal retrieval pairs |
| Mean retrieval latency, Hybrid + RRF | 14.733 ms | `results/benchmark_2026.json` |
| Retrieval v2 Recall@5, dense FAISS | 74.58% | synthetic v2, `n=135` queries |
| Retrieval v2 Recall@5, sparse | 84.17% | synthetic v2, `n=135` queries |
| Retrieval v2 Recall@5, hybrid RRF | 86.25% | synthetic v2, `n=135` queries |
| Retrieval v2 Recall@5, hybrid + rerank | 90.42% | synthetic v2, `n=135` queries; reranking opt-in due latency |
| Retrieval v2 duplicate ratio / leakage | 0.0000 / 0 | synthetic v2 corpus and scope checks |
| Retrieval v2 mean / p95 latency, dense FAISS | 39.99 ms / 48.93 ms | canonical synthetic v2 portfolio gate |
| Retrieval v2 mean / p95 latency, sparse | 9.78 ms / 11.95 ms | canonical synthetic v2 portfolio gate |
| Retrieval v2 mean / p95 latency, hybrid RRF | 55.70 ms / 67.43 ms | canonical synthetic v2 portfolio gate |
| Retrieval v2 mean / p95 latency, hybrid + rerank | 244.36 ms / 287.63 ms | canonical synthetic v2 portfolio gate; reranking opt-in |

These are demo/internal benchmark artifacts, not clinical evidence. See [EVALUATION.md](EVALUATION.md) and [BENCHMARKS.md](BENCHMARKS.md).

Offline grounded-generation scores are evaluator infrastructure self-tests only. They are generated by feeding expected answers and expected citations back into the evaluator. They do not measure LLM answer quality.

## Repository Structure

```text
backend/                 FastAPI app, service layer, models, migrations, tests
backend/app/data/        Small synthetic benchmark datasets retained for reproducibility
docs/                    Architecture notes, ADRs, release notes, implementation docs
examples/                Sample scripts and synthetic sample documents
frontend/public/         Static Web Components frontend
monitoring/              Prometheus/Grafana demo configuration
nginx/                   Reverse proxy config
notebooks/               Exploratory analysis notebooks
results/                 Committed benchmark reports; generated outputs are ignored
scripts/                 Local helpers, quality gates, demo seeders, ops scripts
```

Generated local indexes, uploads, coverage files, caches, virtualenvs, and local databases are ignored and should not be committed.

## Known Limitations

- The project has not undergone prospective clinical validation or clinician usability testing.
- Benchmark datasets are synthetic or small internal demo datasets.
- The default embedding model is general-purpose, not clinical-domain-specific.
- `deterministic-local` embeddings are used for deterministic offline tests and are not semantic production embeddings. Semantic retrieval benchmarks should report the actual embedding backend and model used.
- Production deployment would require managed secrets, TLS, hardened networking, backups, access review, incident response, and compliance governance outside this repository.
- FAISS/local storage defaults are not horizontally scaled.
- Some docs under `docs/` preserve implementation history and ADR context; current limitations are summarized in [LIMITATIONS.md](LIMITATIONS.md).

## Roadmap

The multi-horizon developmental roadmap is tracked separately in **[ROADMAP.md](ROADMAP.md)**:
- **Horizon 1 (Short-Term)**: Robust Agent Safety Guardrails, Local GPU Model Workloads & Quantization.
- **Horizon 2 (Medium-Term)**: Interactive Cost Telemetry Dashboards, Advanced Evaluation Tooling & Synthetic Benchmarks.
- **Horizon 3 (Long-Term)**: FHIR-Compliant Bundle Export, Horizontal Retrieval Scaling.

## License and Citation

MIT License.

```bibtex
@software{clinical_graphrag_pro_2026,
  author = {Mohammad Javad Asgari},
  title = {Clinical GraphRAG Pro},
  year = {2026},
  url = {https://github.com/mohamad679/clinical-graphrag-pro}
}
```
