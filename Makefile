.PHONY: dev build up down logs test lint clean

# ── Development ──────────────────────────────────────────

dev:  ## Start development stack with hot-reload
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

dev-backend:  ## Start only backend in dev mode
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend:  ## Start only frontend in dev mode
	cd frontend && npm run dev

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
	cd backend && python -m pytest -v

test-cov:  ## Run tests with coverage
	cd backend && python -m pytest --cov=app --cov-report=term-missing

lint:  ## Run linters
	cd backend && ruff check app/
	cd frontend && npx tsc --noEmit

# ── Database ─────────────────────────────────────────────

db-migrate:  ## Run database migrations
	cd backend && alembic upgrade head

db-reset:  ## Reset database
	docker compose down -v postgres
	docker compose up -d postgres
	sleep 3
	cd backend && alembic upgrade head

# ── Cleanup ──────────────────────────────────────────────

clean:  ## Remove all containers, images, and volumes
	docker compose down -v --rmi local

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
