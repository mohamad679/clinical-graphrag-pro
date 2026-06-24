# Walkthrough

This walkthrough is aligned to the current repository implementation.

## Main User Flows

1. Chat with retrieval
- Upload a supported document (`.pdf`, `.txt`, `.md`, `.csv`).
- Ask questions in chat.
- Receive safe-buffered SSE streaming responses with sources and reasoning events.

2. Image-assisted chat
- Upload a medical image.
- Trigger image analysis.
- Ask image-specific questions; chat routes through image context flow.

3. Agent workflows
- Use `/api/agents/run` from the Workflows UI view.
- Observe streamed reasoning/tool-call events.

4. Evaluation and admin views
- Inspect evaluation endpoints and admin metrics/health/session/config endpoints (admin auth required).

## Key Implementation Notes

- Frontend is static JS web components in `frontend/public`.
- Backend retrieval is hybrid-capable (vector + BM25 + optional reranking).
- Document deletions invalidate retrieval entries (vector and BM25 tombstones).
- Security hardening includes admin auth enforcement and frontend sanitization safeguards.

## Current Quality Flow

- Phase checks: `./scripts/quality/phase_check.sh <phase>`
- Stable backend gate: `bash scripts/quality/backend_gate.sh`
- CI: `.github/workflows/backend-quality.yml`

## Legacy Material

Older roadmap/demo narratives that reference React/Next.js-specific paths or obsolete implementation stages were removed in favor of this implementation-accurate walkthrough.
