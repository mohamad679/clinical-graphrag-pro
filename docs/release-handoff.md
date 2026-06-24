# Release Handoff (2026-03-17)

This document is the implementation handoff after completing all remediation phases.

## 1) Final State

- Phase status: 8/8 completed.
- Security, correctness, retrieval, runtime reliability, quality gates, and docs alignment were remediated.
- Release-readiness validation passes, including regression checks for phases 2 through 7.

## 2) Mandatory Pre-Deploy Checks

Run from repository root:

```bash
./scripts/quality/phase_check.sh 8
```

Expected outcome:
- Phase 8 checks pass.
- Phase 2-7 regression checks pass.
- Backend stable gate passes.
- Docker Compose config parses successfully (when Docker is installed).

## 3) Runtime Configuration Requirements

Set these explicitly for production:

- `ENABLE_DEMO_AUTH=false`
- Strong `JWT_SECRET_KEY` (at least 32 characters)
- `DEBUG=false`
- Restrictive `CORS_ORIGINS` for trusted frontend origins only

Validate `.env` values against `.env.example` before deployment.

## 4) Deployment Flow

1. Build and start:
```bash
docker compose up --build -d
```
2. Verify API health and app routes.
3. Perform smoke checks on:
- Admin auth protections
- Document upload/delete lifecycle
- Chat retrieval responses
- Frontend API connectivity

## 5) Rollback and Safety

- Use container image tags for reversible deploys.
- Keep previous image and compose bundle available.
- If errors appear post-deploy, roll back to prior image set and re-run `./scripts/quality/phase_check.sh 8` in staging before retry.

## 6) Non-Blocking Warnings Observed

Current quality-gate run may show dependency warnings (for example `networkx` future warning and FAISS swig deprecation warnings). These are non-blocking and did not fail tests.

## 7) Handoff Artifacts

- Plan and progress:
  - `docs/remediation-plan.md`
  - `docs/phase-status.md`
- Release checklist:
  - `docs/release-readiness.md`
- Quality gate scripts:
  - `scripts/quality/phase_check.sh`
  - `scripts/quality/backend_gate.sh`
  - `scripts/quality/release_readiness.sh`
