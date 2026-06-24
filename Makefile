.PHONY: install dev build up down logs test coverage lint run-demo demo clean report verify-final demo-offline demo-live-google demo-live-ollama llm-health demo-report evaluate-retrieval evaluate-rag secrets-check docs-check frontend-build

PYTHON ?= python3
BACKEND_PY := backend/.venv/bin/python
BACKEND_PYTEST_ENV := DEBUG=false ENABLE_DEMO_AUTH=true

# ── Development ──────────────────────────────────────────

install:  ## Install backend dependencies into backend/.venv
	$(PYTHON) -m venv backend/.venv
	backend/.venv/bin/python -m pip install --upgrade pip
	backend/.venv/bin/python -m pip install -r backend/requirements.txt

dev:  ## Start development stack with hot-reload
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

dev-backend:  ## Start only backend in dev mode
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

dev-frontend:  ## Start only frontend in dev mode
	@echo "Frontend is static (nginx-served). Use: docker compose up web"

# ── Production ───────────────────────────────────────────

build:  ## Build production images
	docker compose build

up:  ## Start production stack
	docker compose up -d

down:  ## Stop all services
	docker compose down

restart:  ## Restart all services
	docker compose restart

# ── Monitoring ───────────────────────────────────────────

logs:  ## Follow all container logs
	docker compose logs -f

logs-api:  ## Follow backend logs
	docker compose logs -f api

logs-web:  ## Follow frontend logs
	docker compose logs -f web

ps:  ## List running services
	docker compose ps

health:  ## Check API health
	@curl -s http://localhost/api/health | python3 -m json.tool || echo "API not reachable"

# ── Testing ──────────────────────────────────────────────

test:  ## Run all tests
	cd backend && $(BACKEND_PYTEST_ENV) .venv/bin/pytest -v

coverage:  ## Run tests with coverage
	cd backend && $(BACKEND_PYTEST_ENV) .venv/bin/pytest --cov=app --cov-report=term-missing --cov-report=xml --cov-fail-under=60

test-cov: coverage

lint:  ## Run linters
	cd backend && .venv/bin/python -m ruff check app/ tests/ --ignore=E402,E701,E741,F401,F841
	@echo "No frontend TypeScript project detected; skipping tsc."

run-demo:  ## Seed demo data into a running local stack
	$(PYTHON) scripts/demo/seed_demo_data.py

demo: run-demo

report:  ## Generate the clinical GraphRAG compilation report
	backend/.venv/bin/python scripts/generate_report.py

# ── Database ─────────────────────────────────────────────

db-migrate:  ## Run database migrations
	cd backend && .venv/bin/python -m alembic upgrade head

db-reset:  ## Reset database
	docker compose down -v postgres
	docker compose up -d postgres
	sleep 3
	cd backend && .venv/bin/python -m alembic upgrade head

# ── Cleanup ──────────────────────────────────────────────

clean:  ## Remove local caches and generated runtime artifacts
	docker compose down -v --remove-orphans || true
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '.pytest_cache' -type d -prune -exec rm -rf {} +
	find . -name '.mypy_cache' -type d -prune -exec rm -rf {} +
	find . -name '.ruff_cache' -type d -prune -exec rm -rf {} +
	rm -rf .coverage coverage.xml htmlcov backend/.coverage backend/coverage.xml backend/htmlcov demo_live.db data/vector_store/* data/bm25_store/*

# ── Verification Gate ────────────────────────────────────

verify-final: clean install lint test coverage  ## Run full local verification gate and evaluation scripts
	cd backend && .venv/bin/pytest tests/test_vector_cache.py --no-cov
	cd backend && .venv/bin/pytest tests/test_redaction.py --no-cov
	DATABASE_URL=sqlite+aiosqlite:///demo_live.db backend/.venv/bin/python scripts/run_live_demo.py --provider retrieval-only --strict
	DATABASE_URL=sqlite+aiosqlite:///demo_live.db backend/.venv/bin/python scripts/evaluate_retrieval.py
	DATABASE_URL=sqlite+aiosqlite:///demo_live.db backend/.venv/bin/python scripts/evaluate_rag.py
	backend/.venv/bin/python backend/scripts/load_test.py --dry-run
	@echo "=================================================="
	@echo "  ALL VERIFICATION CHECKS PASSED SUCCESSFULLY!"
	@echo "=================================================="

# ── Live & Offline Demos ─────────────────────────────────

demo-offline:  ## Run the end-to-end demo offline in retrieval-only mode
	DATABASE_URL=sqlite+aiosqlite:///demo_live.db $(BACKEND_PY) scripts/run_live_demo.py --provider retrieval-only

demo-live-google:  ## Run the end-to-end demo using Google Gemini
	DATABASE_URL=sqlite+aiosqlite:///demo_live.db $(BACKEND_PY) scripts/run_live_demo.py --provider gemini

demo-live-ollama:  ## Run the end-to-end demo using local Ollama model
	DATABASE_URL=sqlite+aiosqlite:///demo_live.db $(BACKEND_PY) scripts/run_live_demo.py --provider ollama

llm-health:  ## Run health checks for active LLM provider
	$(BACKEND_PY) -c "import asyncio, sys; from pathlib import Path; sys.path.insert(0, str(Path.cwd()/'backend')); from app.services.llm import llm_service; print(asyncio.run(llm_service.health_check()))"

evaluate-retrieval:  ## Run retrieval quality evaluation
	DATABASE_URL=sqlite+aiosqlite:///demo_live.db $(BACKEND_PY) scripts/evaluate_retrieval.py

evaluate-rag:  ## Run RAG quality and safety evaluation
	DATABASE_URL=sqlite+aiosqlite:///demo_live.db $(BACKEND_PY) scripts/evaluate_rag.py

secrets-check:  ## Run credentials and security leakage checks
	$(BACKEND_PY) scripts/check_release_integrity.py

docs-check:  ## Verify documentation integrity and claims
	$(BACKEND_PY) -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path.cwd()/'scripts')); from check_release_integrity import check_docs_integrity; errs = check_docs_integrity(); [print(e) for e in errs]; sys.exit(1 if errs else 0)"

frontend-build:  ## Validate frontend static assets deployment readiness
	@echo "Frontend is composed of pure static assets in frontend/public/. No compilation required."

demo-report:  ## Show the generated live demo reports
	@cat reports/live_demo_retrieval-only.md || echo "No retrieval-only report found."
	@cat reports/live_demo_gemini.md || echo "No gemini report found."

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
