# Quickstart Guide

This guide provides instructions to run Clinical GraphRAG Pro from a fresh clone. Follow these steps to set up the environment, run local services, execute the test suite, and start the development servers.

---

## 1. Prerequisites

Ensure you have the following installed on your host machine:
- **Python**: Version 3.10 or 3.11.
- **Docker & Docker Compose**: For running containerized services (PostgreSQL, Redis, Neo4j).
- **Node.js & npm**: If running the frontend outside of Docker.
- **Make**: For running convenience tasks.

---

## 2. Initial Setup

1. **Clone the Repository** (if not already done):
   ```bash
   git clone https://github.com/mohamad679/clinical-graphrag-pro.git
   cd clinical-graphrag-pro
   ```

2. **Configure Environment Variables**:
   Copy the sample environment configuration template files:
   ```bash
   cp .env.example .env
   cp .env.example backend/.env
   ```
   
   > [!IMPORTANT]
   > For local development, update the following fields in `backend/.env`:
   > - `JWT_SECRET`: Generate a secure key (e.g., `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`).
   > - Add `GROQ_API_KEY` or `GOOGLE_API_KEY` if you plan to perform live LLM calls (otherwise, mock/debug providers will be used).

3. **Install Dependencies**:
   Use `make` to initialize the Python virtual environment and install backend dependencies:
   ```bash
   make install
   ```
   This creates a virtual environment at `backend/.venv` and installs packages.

---

## 3. Running Local Services (Docker)

To start the database, Redis, and other required services, run:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

This command builds and runs the following in the background:
- **db**: PostgreSQL (stores auth data, sessions, and audits).
- **redis**: Redis (caching and Celery task broker).
- **neo4j**: Neo4j (stores the clinical graph).
- **backend**: FastAPI app running on `http://localhost:8000`.
- **frontend**: Static server exposing the web interface on `http://localhost:3000`.

To view service logs, run:
```bash
docker compose logs -f
```

---

## 4. Seeding Demo Data

Once services are running, seed the database and vector indexes with sample clinical documentation, patient records, and graph relations:

```bash
make demo
```

---

## 5. Running the Test Suite

To verify that the installation succeeded and all security/retrieval components function correctly, execute:

```bash
make test
```

For coverage reports:
```bash
make coverage
```
This runs `pytest` inside the backend virtual environment, verifying patient tenant isolation, structured schemas, RAG pipelines, and agent reasoning loops.

---

## 6. Project Access Points

- **Web UI**: `http://localhost:3000` (or `http://localhost` if running through Nginx proxy).
- **Interactive API Docs (Swagger)**: `http://localhost:8000/docs` (internal) or `http://localhost/api/docs`.
- **Prometheus Metrics**: `http://localhost:9090` (if monitoring compose file is launched).
- **FastAPI Custom Operational Metrics**: `http://localhost:8000/api/v1/metrics` or `/admin/metrics`.
