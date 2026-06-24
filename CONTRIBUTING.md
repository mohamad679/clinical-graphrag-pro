# Contributing to Clinical GraphRAG Pro

Thanks for contributing. This guide matches the current repository implementation.

## Prerequisites

- Python 3.11+ (3.12 recommended)
- Docker + Docker Compose
- Git

Frontend note:
- The frontend in this repository is static (`frontend/public`) and nginx-served.
- Node.js is optional unless you are introducing new JS tooling.

## Setup

```bash
git clone https://github.com/your-username/clinical-graphrag-pro.git
cd clinical-graphrag-pro
cp .env.example .env

python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
```

## Running

Docker stack:

```bash
make dev
```

Backend only:

```bash
make dev-backend
```

## Testing and Linting

Run repository checks:

```bash
make test
make lint
```

Run phased checks:

```bash
./scripts/quality/phase_check.sh 1
./scripts/quality/phase_check.sh 2
```

Run backend stable quality gate:

```bash
bash scripts/quality/backend_gate.sh
```

Optional heavy tests (fine-tune paths):

```bash
RUN_HEAVY_TESTS=true make test
```

## Code Standards

Backend:
- Add type hints on public functions.
- Keep async I/O async.
- Prefer focused services in `backend/app/services`.
- Add tests for behavior changes.

Frontend:
- Keep static assets/components in `frontend/public`.
- Avoid unsafe `innerHTML` interpolation of untrusted content.

## Project Structure

- `backend/app/api/`: FastAPI routers.
- `backend/app/services/`: business logic.
- `backend/app/core/`: configuration, auth, infra.
- `backend/tests/`: test suites.
- `frontend/public/js/components/`: frontend web components.
- `scripts/quality/`: quality and phase gates.

## Pull Requests

1. Create a branch from `main`.
2. Keep changes scoped and tested.
3. Ensure `bash scripts/quality/backend_gate.sh` passes locally.
4. Update docs when behavior or commands change.

## Commit Messages

Use clear conventional-style messages, for example:

- `feat: add admin auth enforcement for metrics routes`
- `fix: sanitize markdown links in chat renderer`
- `docs: align README with static frontend runtime`

## Benchmark Integrity

- Never report a benchmark result that was generated with 
  OFFLINE_DEMO_MODE=true or EMBEDDING_MODEL=deterministic-local.
- Always include n (sample size) next to every metric.
- If a benchmark could not be run (e.g., no API credentials), 
  report it as N/A with the reason, not as 0% or omit it.
- Retrieval metrics on synthetic in-distribution queries are 
  smoke tests, not quality proofs. Label them accordingly.

## License

By contributing, you agree contributions are under MIT.
