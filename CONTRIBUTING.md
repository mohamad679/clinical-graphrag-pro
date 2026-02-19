# Contributing to Clinical GraphRAG Pro

Thank you for your interest in contributing! This guide will help you get started.

---

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose
- Git

### Quick Setup

```bash
# Clone the repository
git clone https://github.com/your-username/clinical-graphrag-pro.git
cd clinical-graphrag-pro

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install

# Configure environment
cp ../.env.example .env
# Edit .env with your API keys
```

### Running for Development

```bash
# Option A: Docker (recommended)
make dev

# Option B: Manual
# Terminal 1 — Backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
```

---

## Code Standards

### Python (Backend)

- **Formatter:** `ruff format`
- **Linter:** `ruff check`
- **Type hints:** Required on all function signatures
- **Docstrings:** Required on all public classes and functions
- **Async:** Use `async/await` for I/O-bound operations

### TypeScript (Frontend)

- **Type checker:** `npx tsc --noEmit`
- **Strict mode:** Enabled
- **Components:** Functional components with hooks
- **API types:** Define in `src/lib/api.ts`

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add drug interaction checker tool
fix: correct BM25 tokenization for hyphenated terms
docs: update API reference with eval endpoints
test: add model registry deployment tests
```

---

## Testing

```bash
# Run all tests
make test

# Run specific file
cd backend && python -m pytest tests/test_auth.py -v

# Run with coverage
make test-cov

# Frontend type check
cd frontend && npx tsc --noEmit
```

### Writing Tests

- Place tests in `backend/tests/test_*.py`
- Use `pytest.mark.anyio` for async API tests
- Use `pytest.mark.asyncio` for async unit tests
- Use shared fixtures from `conftest.py`

---

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `backend/app/api/` | FastAPI routers (HTTP layer) |
| `backend/app/services/` | Business logic (service layer) |
| `backend/app/core/` | Infrastructure (auth, config, logging) |
| `backend/tests/` | Python tests |
| `frontend/src/components/` | React components |
| `frontend/src/lib/` | API client and utilities |
| `docs/` | Project documentation |
| `nginx/` | Reverse proxy configuration |

---

## Adding a New Feature

1. **Backend service:** Create `backend/app/services/your_feature.py`
2. **API router:** Create `backend/app/api/your_feature.py`
3. **Register router** in `backend/app/main.py`
4. **Frontend types:** Add types/functions to `frontend/src/lib/api.ts`
5. **Frontend component:** Create `frontend/src/components/YourPanel.tsx`
6. **Add navigation** in `Sidebar.tsx` and routing in `page.tsx`
7. **Write tests** in `backend/tests/test_your_feature.py`
8. **Update docs** in `docs/API.md`

---

## Pull Request Process

1. Create a feature branch from `main`
2. Make changes following the code standards
3. Ensure all tests pass: `make test`
4. Ensure linting passes: `make lint`
5. Update documentation if needed
6. Submit a PR with a clear description

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
