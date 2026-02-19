<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009485?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=next.js&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" />
  <img src="https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white" />
</p>

# 🏥 Clinical GraphRAG Pro

> Enterprise-grade Retrieval-Augmented Generation platform for clinical and biomedical documents, featuring knowledge graph integration, agentic workflows, multimodal vision, fine-tuning, and production-ready deployment.

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🔍 **Hybrid RAG** | FAISS vector + BM25 keyword search with RRF fusion and cross-encoder reranking |
| 🧠 **Knowledge Graph** | UMLS-style medical entity extraction and relationship mapping |
| 🤖 **Agentic Workflows** | ReAct-pattern agent with 7 medical tools (calculators, drug lookup, search) |
| 👁️ **Multimodal Vision** | Medical image analysis — X-rays, pathology, dermatology with clinical reports |
| 🧪 **Evaluation Framework** | 4 metrics: Faithfulness, Relevance, Citation Accuracy, Context Precision |
| 🔧 **LoRA Fine-Tuning** | Dataset management, simulated/real training, model registry with deployment |
| 🔐 **Production Security** | JWT authentication, token-bucket rate limiting, structured JSON logging |
| 📊 **Admin Dashboard** | Real-time health monitoring, API metrics, session tracking, configuration |
| 🐳 **Docker Ready** | Multi-stage builds, Nginx reverse proxy, CI/CD pipeline |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (Port 80)                           │
│              ┌──────────┬──────────────┐                    │
│              │  /api/*   │      /       │                    │
└──────────────┼──────────┼──────────────┼────────────────────┘
               ▼          │              ▼
┌──────────────────────┐  │  ┌──────────────────────┐
│   FastAPI Backend    │  │  │   Next.js Frontend   │
│   (Port 8000)        │  │  │   (Port 3000)        │
│                      │  │  │                      │
│  ┌────────────────┐  │  │  │  ┌────────────────┐  │
│  │ Auth Middleware │  │  │  │  │ ChatInterface  │  │
│  │ Rate Limiter   │  │  │  │  │ DocumentPanel  │  │
│  │ Request Logger │  │  │  │  │ WorkflowPanel  │  │
│  ├────────────────┤  │  │  │  │ ImageGallery   │  │
│  │ 10 API Routers │  │  │  │  │ EvalPanel      │  │
│  ├────────────────┤  │  │  │  │ FineTunePanel  │  │
│  │ 14 Services    │  │  │  │  │ SettingsPanel  │  │
│  └───────┬────────┘  │  │  │  │ AnalysisPanel  │  │
│          │           │  │  │  └────────────────┘  │
└──────────┼───────────┘  │  └──────────────────────┘
           │              │
     ┌─────┼─────┐        │
     ▼     ▼     ▼        │
  ┌─────┬─────┬───────┐   │
  │FAISS│BM25 │ UMLS  │   │
  │Index│Index│ Graph  │   │
  └─────┴─────┴───────┘   │
                           │
  ┌────────┐  ┌────────┐   │
  │Postgres│  │ Redis  │   │
  └────────┘  └────────┘   │
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose (for containerized setup)

### Option 1: Docker (Recommended)

```bash
# Clone and configure
git clone https://github.com/your-username/clinical-graphrag-pro.git
cd clinical-graphrag-pro
cp .env.example backend/.env

# Edit backend/.env with your API keys
# GROQ_API_KEY=your-key-here

# Start all services
make build
make up

# Open http://localhost
```

### Option 2: Local Development

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev

# Open http://localhost:3000
```

### Option 3: Full Dev Stack (Docker + Hot Reload)

```bash
make dev
```

---

## 📁 Project Structure

```
clinical-graphrag-pro/
├── backend/
│   ├── app/
│   │   ├── api/              # 10 API routers
│   │   │   ├── admin.py      # Auth, health, metrics, config
│   │   │   ├── agents.py     # Agentic workflow endpoints
│   │   │   ├── chat.py       # Sync/streaming chat
│   │   │   ├── documents.py  # Upload, list, delete
│   │   │   ├── eval.py       # RAG evaluation
│   │   │   ├── fine_tune.py  # Dataset/training/model APIs
│   │   │   ├── graph.py      # Knowledge graph queries
│   │   │   ├── health.py     # Health check
│   │   │   └── images.py     # Medical image analysis
│   │   ├── core/             # Infrastructure
│   │   │   ├── auth.py       # JWT authentication
│   │   │   ├── config.py     # Pydantic settings
│   │   │   ├── logging_config.py  # Structured logging
│   │   │   └── rate_limiter.py    # Token-bucket limiter
│   │   ├── services/         # 14 business services
│   │   │   ├── agent.py      # ReAct agent orchestrator
│   │   │   ├── bm25_index.py # BM25 sparse search
│   │   │   ├── datasets.py   # Fine-tune dataset management
│   │   │   ├── evaluation.py # 4-metric RAG evaluation
│   │   │   ├── fine_tune.py  # LoRA training orchestrator
│   │   │   ├── image_processing.py  # Image utilities
│   │   │   ├── llm.py        # Multi-provider LLM client
│   │   │   ├── model_registry.py    # Adapter versioning
│   │   │   ├── query_engine.py      # Hybrid search engine
│   │   │   ├── rag.py        # RAG pipeline
│   │   │   ├── reranker.py   # Cross-encoder reranker
│   │   │   ├── tool_registry.py     # 7 medical tools
│   │   │   ├── vector_store.py      # FAISS + chunking
│   │   │   └── vision.py     # Medical image analysis
│   │   └── main.py           # FastAPI app entry point
│   ├── tests/                # 87 tests
│   ├── Dockerfile            # Multi-stage production build
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/page.tsx      # Main layout + routing
│   │   ├── components/       # 13 React components
│   │   └── lib/api.ts        # Typed API client
│   └── Dockerfile            # Next.js standalone build
├── nginx/nginx.conf          # Reverse proxy config
├── docker-compose.yml        # Production (5 services)
├── docker-compose.dev.yml    # Dev overrides
├── .github/workflows/ci.yml  # CI/CD pipeline
├── Makefile                  # 15 developer targets
└── .env.example              # Configuration template
```

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | JWT login |
| `GET` | `/api/auth/me` | Current user info |
| `GET` | `/api/health` | Service health check |
| `POST` | `/api/chat/sync` | Synchronous chat |
| `POST` | `/api/chat/stream` | Streaming chat (SSE) |
| `POST` | `/api/documents/upload` | Upload PDF/TXT/MD |
| `GET` | `/api/documents` | List documents |
| `GET` | `/api/graph/stats` | Knowledge graph stats |
| `GET` | `/api/graph/search` | Graph search |
| `POST` | `/api/images/analyze` | Analyze medical image |
| `GET` | `/api/agents/tools` | List available tools |
| `POST` | `/api/agents/run` | Run agentic workflow |
| `POST` | `/api/eval/run` | Evaluate RAG quality |
| `GET` | `/api/eval/history` | Evaluation history |
| `GET` | `/api/fine-tune/datasets` | List datasets |
| `POST` | `/api/fine-tune/jobs` | Start training job |
| `GET` | `/api/fine-tune/models` | Model registry |
| `GET` | `/api/admin/health` | Detailed system health |
| `GET` | `/api/admin/metrics` | Request metrics |

> Full API docs available at `/docs` (Swagger UI) or `/redoc`.

---

## 🧪 Testing

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
cd backend && python -m pytest tests/test_auth.py -v
```

| Test Suite | Tests | Coverage |
|------------|-------|----------|
| API endpoints | 8 | Root, Health, Documents, Chat, Graph |
| Agent & Tools | 7 | Tool registry, Workflow API |
| Advanced RAG | 15 | Chunking, BM25, RRF, Config |
| Auth & Security | 21 | JWT, Passwords, Rate Limiter, Sessions |
| Admin API | 13 | Login, Health, Metrics, Config |
| Eval & Fine-Tune | 20 | Metrics, Datasets, Training, Registry |
| Integration | 3 | Auth flow, Pipeline, Smoke tests |
| **Total** | **87** | |

---

## ⚙️ Configuration

Copy `.env.example` to `backend/.env` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes* | Groq API key for LLM |
| `GOOGLE_API_KEY` | Yes* | Google Gemini API key |
| `JWT_SECRET` | Yes | JWT signing secret |
| `DATABASE_URL` | No | PostgreSQL connection string |
| `REDIS_URL` | No | Redis connection string |
| `RATE_LIMIT_PER_MINUTE` | No | Rate limit (default: 60) |

*At least one LLM provider required.

---

## 🛠️ Makefile Commands

```bash
make dev         # Start dev stack with hot-reload
make build       # Build production images
make up          # Start production stack
make down        # Stop all services
make test        # Run pytest
make lint        # Run ruff + tsc
make logs        # Follow container logs
make health      # Check API health
make db-migrate  # Run database migrations
make clean       # Remove containers + volumes
make help        # Show all commands
```

---

## 📂 Technical Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12, FastAPI, Uvicorn, Pydantic |
| **Frontend** | Next.js 15, React 19, TypeScript |
| **Database** | PostgreSQL 16, SQLAlchemy, Alembic |
| **Cache** | Redis 7 |
| **Search** | FAISS (vector), BM25 (keyword), Cross-Encoder (reranking) |
| **AI/ML** | Groq, Google Gemini, Sentence-Transformers, Unsloth/PEFT |
| **Auth** | PyJWT, Token-bucket rate limiting |
| **DevOps** | Docker, Nginx, GitHub Actions |
| **Testing** | Pytest, HTTPX, pytest-asyncio |

---

## 🗺️ Roadmap

- [x] **Phase 1-2**: Foundation & Migration (FastAPI + Next.js + PostgreSQL)
- [x] **Phase 3**: Vision & Multimodal (Medical image analysis)
- [x] **Phase 4**: Agentic Workflows (ReAct agent + tool registry)
- [x] **Phase 5**: Advanced RAG (Hybrid search + reranking + evaluation)
- [x] **Phase 6**: Fine-Tuning (LoRA training + model registry)
- [x] **Phase 7**: Production Features (Auth + rate limiting + logging + admin)
- [x] **Phase 8**: Deployment & DevOps (Docker + Nginx + CI/CD)
- [x] **Phase 9**: Testing & QA (87 tests)
- [x] **Phase 10**: Documentation & Portfolio

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>Built with ❤️ for Clinical AI</strong>
</p>
