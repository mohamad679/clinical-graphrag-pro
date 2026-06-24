# Release Notes — Clinical GraphRAG Pro (v1.0.0)

Clinical GraphRAG Pro is a clinical AI systems portfolio and research engineering platform. It is designed as an educational reference architecture for secure, verifiable, and tenant-isolated Retrieval-Augmented Generation (RAG) over medical text, structured FHIR records, and clinical image files.

> [!CAUTION]
> **No Clinical Validation**: This codebase is a demonstration of AI systems engineering architecture and has NOT undergone clinical validation. It is not approved for diagnostic use, treatment decision support, or direct patient care.

---

## 🚀 What's New in v1.0.0

The v1.0.0 release hardens and packages the entire multi-phase clinical RAG pipeline:
1. **Multi-Tenancy & Tenant Isolation**: Rigid scoping of all vector, BM25, and Graph context operations to specific tenant and patient boundaries, preventing cross-tenant data leakage.
2. **Safety Adjudication Flow**: Implement RAG response post-validation and a one-time regeneration block. If inline citations are violated, hallucinated, or lack graph provenance, the response is rejected and falls back to a safe clinical abstention.
3. **Hybrid Search & Fusion**: Dense FAISS vector retrieval combined with sparse BM25 indexing, fused via Reciprocal Rank Fusion (RRF) and re-ranked using Cross-Encoder models.
4. **Multimedia Integration**: Ingestion support for medical images and audio files, with dynamic DICOM scrubbing and metadata scrubbing (PHI removal) before saving files.
5. **Durable Worker Pipelines**: Celery task runners managing fine-tuning, training dataset generation, and asynchronous ingestion with proper state-tracking, retries, and backoff.
6. **Observability & Health Gates**: Dynamic Prometheus metrics tracking token counts, latencies, and provider errors, with custom endpoints and visual dashboards.

---

## 🛠️ How to Run & Verify

### 1. Verification Gate (Reviewer Clean Path)
To clean, build, lint, and run all validation tests (including retrieval and RAG quality checks, load test dry-runs, and offline demo validation):
```bash
make verify-final
```

### 2. Standalone Commands
- **Install Dependencies**: `make install`
- **Run Linting**: `make lint`
- **Run Backend Tests**: `make test`
- **Run Test Coverage**: `make coverage`
- **Run Offline Demo**: `make demo-offline`
- **Retrieve Evaluation Results**: `make evaluate-retrieval`
- **Run RAG Quality Check**: `make evaluate-rag`
- **Security & Secrets Check**: `make secrets-check`
- **Verify Docs**: `make docs-check`

---

## 🤖 Live Demo Instructions

### Google Gemini Setup
To run the live demo with Google Gemini, set up your API key and model config in `.env` (or set them in your active terminal session):
```bash
export GEMINI_API_KEY="<set-your-key-in-your-shell-or-secret-manager>"
export LLM_PROVIDER="gemini"
make demo-live-google
```
The demo will run queries, validate citations, compile performance metrics, and output a detailed Markdown report at `reports/live_demo_gemini.md`.

### Local Ollama Setup
To run the live demo using a local Ollama model (e.g., Llama 3):
1. Start Ollama: `ollama serve`
2. Pull the model: `ollama pull llama3`
3. Run:
```bash
make demo-live-ollama
```

---

## ⚠️ What is Intentionally NOT Claimed

To maintain strict technical credibility and compliance honesty, the following claims are **explicitly denied** and marked as out of scope:
- **HIPAA-Compliance**: The codebase implements local security practices (RBAC, audit logs, file validation) but is **not** certified under HIPAA, SOC 2, or any regulatory framework.
- **Clinical Validation**: No prospective validation has been done. The golden dataset is synthetic and does not represent real USMLE or MedQA questions.
- **SOTA / Frontier Model Performance**: The platform acts as a scaffolding engine to demonstrate systems engineering. Retrieval hit-rates and LLM responses are benchmarks for regression checking and demo purposes only.

---

## 🗺️ Roadmap & Next Steps

For information on the multi-horizon timeline of this project (including planned integrations, production hardening steps, and research directions), please consult the [ROADMAP.md](ROADMAP.md) file.
