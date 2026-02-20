# 🏥 Clinical GraphRAG Pro

![Application Screenshot](./dashboard-preview.png)

Clinical GraphRAG Pro is an enterprise-grade medical AI platform combining traditional Retrieval-Augmented Generation (RAG) with Knowledge Graphs to provide highly accurate, explainable, and context-aware analysis of medical documents.

## ✨ Features

- **Hybrid Search RAG**: Combines semantic embeddings (SentenceTransformers) with keyword search (BM25) for high-recall medical document retrieval.
- **Multimodal Document Understanding**: Upload PDFs, DOCX, or medical images (X-rays, MRIs) for direct AI analysis.
- **Agentic Workflows**: Dynamic execution of multi-step medical reasoning tasks (e.g., differential diagnosis, treatment guideline cross-referencing).
- **Explainable AI (XAI)**: Every response includes exactly which document chunks were used and the step-by-step reasoning logic.
- **Dark-Themed UI**: A modern, responsive, professional dashboard built with Next.js, Tailwind CSS, and Framer Motion.

## 🚀 Live Demo

**Frontend (Vercel)**: [https://clinical-graphrag-pro.vercel.app](https://clinical-graphrag-pro.vercel.app)  
**Backend API (Hugging Face)**: [https://mohi679-clinical-graphrag-backend.hf.space](https://mohi679-clinical-graphrag-backend.hf.space)

---

## 🛠️ Architecture & Tech Stack

This project is built using a modern decoupled architecture:

### Frontend
- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS + Custom CSS Variables
- **Animations**: Framer Motion
- **Icons**: Lucide React

### Backend
- **Framework**: FastAPI (Python 3.12)
- **Database**: PostgreSQL with `pgvector` & `age` (Knowledge Graph)
- **Caching**: Redis
- **LLM Engine**: Groq (Llama 3 70B) / Google Gemini
- **Embeddings**: HuggingFace (`all-mpnet-base-v2`)

---

## 💻 Local Development

If you want to run this application on your own machine instead of the cloud, follow these steps:

### Prerequisites
- Docker & Docker Compose
- Node.js (v18+)
- Python (3.12)

### 1. Setup Environment
Clone the repository and set up the backend environment variables:
```bash
git clone https://github.com/mohamad679/clinical-graphrag-pro.git
cd clinical-graphrag-pro/backend

# Copy the example ENV and add your GROQ_API_KEY
cp .env.example .env
```

### 2. Start Services
Use Docker Compose to spin up the Postgres Database (with pgvector/age) and Redis:
```bash
cd ..
docker compose up -d postgres redis
```

### 3. Run Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start FastAPI server on port 8000
uvicorn app.main:app --reload
```

### 4. Run Frontend
In a new terminal:
```bash
cd frontend
npm install

# Start Next.js development server on port 3000
npm run dev
```

The application will now be running locally at `http://localhost:3000`.

---

## 🛡️ License

This project is licensed under the MIT License - see the LICENSE file for details.
