# System Architecture

## High-Level Overview

```
                    ┌──────────────────────┐
                    │      Client          │
                    │  (Browser / Mobile)  │
                    └──────────┬───────────┘
                               │ HTTPS
                    ┌──────────▼───────────┐
                    │    Nginx (Port 80)   │
                    │   Reverse Proxy      │
                    │   + Gzip + Headers   │
                    └────┬────────────┬────┘
                         │            │
                   /api/*│            │ /*
                         │            │
            ┌────────────▼──┐  ┌──────▼────────────┐
            │  FastAPI       │  │  Next.js           │
            │  Backend       │  │  Frontend          │
            │  (Port 8000)   │  │  (Port 3000)       │
            └──────┬─────────┘  └──────────────────  │
                   │                                  │
         ┌─────┬──┴───┬──────┐                        │
         │     │      │      │                        │
         ▼     ▼      ▼      ▼                        │
      ┌─────┬─────┬──────┬───────┐                    │
      │FAISS│BM25 │UMLS  │Groq/  │                    │
      │     │     │Graph │Gemini │                    │
      └─────┴─────┴──────┴───────┘                    │
                   │                                  │
         ┌─────────┴─────────┐                        │
         ▼                   ▼                        │
      ┌────────┐       ┌────────┐                     │
      │Postgres│       │ Redis  │                     │
      │  (DB)  │       │(Cache) │                     │
      └────────┘       └────────┘
```

---

## Backend Architecture

### Middleware Pipeline

```
Request → Rate Limiter → Request Logger → CORS → Router → Response
              │                │
              │                └─→ Metrics Collection
              └─→ 429 if exceeded
```

### Service Layer

| Service | Responsibility |
|---------|---------------|
| `llm.py` | Multi-provider LLM client (Groq, Gemini) |
| `vector_store.py` | FAISS indexing, sentence-aware chunking |
| `bm25_index.py` | BM25 sparse keyword search |
| `query_engine.py` | Hybrid search with RRF fusion |
| `reranker.py` | Cross-encoder reranking |
| `rag.py` | RAG pipeline orchestration |
| `agent.py` | ReAct-pattern agent with tool calls |
| `tool_registry.py` | 7 medical tools (BMI, eGFR, drug lookup, etc.) |
| `vision.py` | Medical image analysis (X-ray, pathology) |
| `image_processing.py` | Image utilities and preprocessing |
| `evaluation.py` | 4-metric RAG quality evaluation |
| `datasets.py` | Training dataset management |
| `fine_tune.py` | LoRA training orchestrator |
| `model_registry.py` | Adapter versioning and deployment |

### Infrastructure Layer

| Module | Responsibility |
|--------|---------------|
| `auth.py` | JWT authentication, demo user seeding |
| `rate_limiter.py` | Token-bucket per-IP rate limiting |
| `logging_config.py` | Structured JSON logging, request metrics |
| `config.py` | Pydantic settings with env loading |

---

## Frontend Architecture

### Component Hierarchy

```
page.tsx (Main Layout)
├── Sidebar.tsx (Navigation — 8 views)
└── Content Area
    ├── ChatInterface.tsx      (RAG chat + streaming)
    ├── DocumentUploader.tsx   (File upload + management)
    ├── AnalysisPanel.tsx      (Knowledge graph visualization)
    ├── WorkflowPanel.tsx      (Agentic workflows)
    ├── ImageGallery.tsx       (Medical image analysis)
    │   └── ImageViewer.tsx    (Detail view)
    ├── EvalPanel.tsx          (Evaluation radar charts)
    ├── FineTunePanel.tsx      (4-tab fine-tuning dashboard)
    ├── SettingsPanel.tsx      (3-tab admin dashboard)
    └── LoginModal.tsx         (Authentication modal)
```

### Design System

- **Theme:** Dark glassmorphism with `rgba` backgrounds and backdrop blur
- **Colors:** Emerald (#10b981) primary, with distinct accent colors per section
- **Charts:** Custom SVG-based (radar, loss curves, gauges)
- **Animations:** CSS transitions + keyframe animations

---

## Data Flow

### RAG Query Pipeline

```
User Query
  │
  ├─→ Query Expansion (LLM)
  │
  ├─→ Vector Search (FAISS, top-k)
  │
  ├─→ Keyword Search (BM25, top-k)
  │
  ├─→ RRF Fusion (combine rankings)
  │
  ├─→ Cross-Encoder Reranking
  │
  ├─→ LLM Generation (with context)
  │
  └─→ Response + Sources
```

### Fine-Tuning Pipeline

```
Documents → Chunk → Auto-Generate QA Pairs → Dataset
  │
  └─→ LoRA Config → Training Job → Metrics → Model Registry → Deploy
```

---

## Deployment

### Docker Services

| Service | Image | Port | Health Check |
|---------|-------|------|-------------|
| `nginx` | nginx:alpine | 80 | — |
| `api` | custom (Python) | 8000 | `/api/health` |
| `web` | custom (Node) | 3000 | wget |
| `postgres` | postgres:16-alpine | 5432 | pg_isready |
| `redis` | redis:7-alpine | 6379 | redis-cli ping |

### CI/CD Pipeline

```
Push → Lint (ruff + tsc) → Test (pytest) → Build (Docker) → Deploy
```
