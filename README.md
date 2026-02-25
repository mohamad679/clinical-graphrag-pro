# 🏥 Clinical GraphRAG Pro (2026 Edition)

![Application Demo](./docs/assets/final_clinical_graphrag_demo_1771618230865.webp)

**Clinical GraphRAG Pro** is a production-grade, multi-agent AI platform built for healthcare. Transitioning from basic "chat over PDF" to a deterministic **Autonomous Medical Reasoning Engine**, it combines advanced Agentic orchestration, Temporal Knowledge Graphs, and an Adversarial Safety Adjudicator to achieve enterprise-level clinical analysis.

---

## 📺 Full Project Walkthrough & Demos
**👉 [Click here to view the full Demo Walkthrough with Videos and Screenshots!](./docs/walkthrough.md)**

---

## 🌟 Core Innovations

### 1. Multi-Agent Orchestration 🧠
At the core of the system is the **Supervisor Agent** (powered by LangChain ReAct loops). Instead of blindly answering questions, the Supervisor delegates tasks to specialized sub-agents:
- **Pharmacovigilance Agent:** Analyzes drug interactions and cross-references them with the Knowledge Graph.
- **Diagnostics Agent:** Ingests extracted symptoms to output weighted differential diagnoses.
- **Data Extraction Agent:** Employs rigid NLP parsing to isolate lab values and dates into pristine JSON.

### 2. Temporal Knowledge Graphs ⏳
We augmented the standard semantic Vector Store with a highly connective **Temporal Knowledge Graph** (powered by `networkx`).
Instead of static chunks, the AI traverses relationships across time (e.g., establishing if Drug X was administered *before* or *after* Symptom Y emerged).

### 3. Adversarial Safety Adjudicator (Red Team) 🛑
To solve the Hallucination problem, the AI actively enforces its own safety boundaries. The Agent never streams directly to the user; it generates a **hidden draft**. This draft is passed to a strict Adjudicator LLM. If the Adjudicator detects hallucinations or lethal advice, the system rejects the draft and streams a specific safety warning to the user.

### 4. Multimodal Vision Diagnostics 👁️
Physicians can upload X-Rays, MRIs, and CT Scans directly into the chat prompt. The Vision LLM processes the image in isolation, detecting the modality, identifying findings, and generating a differential diagnosis.

---

## 🏗️ System Architecture

```mermaid
graph TD
    classDef user fill:#6366f1,stroke:#4338ca,stroke-width:2px,color:#fff;
    classDef agent fill:#8b5cf6,stroke:#7c3aed,stroke-width:2px,color:#fff;
    classDef tool fill:#10b981,stroke:#059669,stroke-width:2px,color:#fff;
    classDef db fill:#f59e0b,stroke:#d97706,stroke-width:2px,color:#fff;
    classDef check fill:#ef4444,stroke:#dc2626,stroke-width:2px,color:#fff;

    User(["👤 User / Clinician"]) ::: user
    User --> |Query + Images/PDFs| Supervisor

    subgraph "Agentic Reasoning Engine (LangChain ReAct)"
        Supervisor{"🤖 Supervisor Agent"} ::: agent
        Supervisor --> |Delegates| Pharm["💊 Pharmacovigilance Worker"] ::: agent
        Supervisor --> |Delegates| Diag["🩺 Diagnostics Worker"] ::: agent
        Supervisor --> |Delegates| Data["📊 Data Extraction Worker"] ::: agent
    end

    subgraph "Retrieval Layer"
        Pharm --> |Queries| Graph[("Temporal Knowledge Graph")] ::: db
        Diag --> |Searches| Vector[("Semantic Vector Store")] ::: db
        Data --> |Parses| Docs["📄 Uploaded Clinical Notes"] ::: tool
    end

    subgraph "Verification Layer"
        Supervisor --> |Proposes Answer| Adjudicator["🛑 Adversarial Adjudicator"] ::: check
        Adjudicator -.-> |Passes| Final["✅ Render Output"] ::: tool
        Adjudicator -.-> |Fails (Hallucination)| Reject["🚫 Intercept & Warn"] ::: tool
    end

    Final --> User
    Reject --> User
```

---

## 🛠️ Tech Stack
- **Frontend**: Next.js 14, TypeScript, Tailwind CSS, Framer Motion
- **Backend**: FastAPI (Python 3.12), SQLAlchemy
- **Databases**: PostgreSQL (`pgvector`), Redis
- **AI Core**: Llama-3-70B / Google Gemini (via Groq API), LangChain, HuggingFace Embeddings
- **Graph Processing**: NetworkX

---

## 💻 Local Development

1. **Clone & Setup Environment**
   ```bash
   git clone https://github.com/mohamad679/clinical-graphrag-pro.git
   cd clinical-graphrag-pro/backend
   cp .env.example .env
   # Add your GROQ_API_KEY and OPENAI_API_KEY to the .env file
   ```

2. **Start Infrastructure (Docker)**
   ```bash
   cd ..
   docker compose up -d postgres redis
   ```

3. **Run the Backend (FastAPI)**
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

4. **Run the Frontend (Next.js)**
   ```bash
   cd ../frontend
   npm install
   npm run dev
   ```

Navigate to `http://localhost:3000` to interact with the Clinical Agent.

---
## 🛡️ License
MIT License

## 📊 Benchmark Results (v2.0)

| Metric | Score | Target | Status |
|--------|-------|--------|--------|
| RAGAS Faithfulness | TBD | >0.95 | 🔄 |
| Answer Relevancy | TBD | >0.85 | 🔄 |
| Adjudicator Precision | TBD | >0.95 | 🔄 |
| Adjudicator Recall | TBD | >0.95 | 🔄 |

## 🆕 What's New in v2.0
- 🧪 Full Evaluation Layer (RAGAS + Adjudicator Benchmark)
- 🕸️ Neo4j Production Graph Database
- 📊 3D Knowledge Graph Visualization  
- 🏥 MIMIC-IV Clinical Data Integration
- 👁️ Observability: LangSmith + Prometheus + structlog
- 🏥 SOAP Note Auto-Generation
- 👍 Human-in-the-Loop CSAT Feedback
- 🔬 Entity Normalization Service
