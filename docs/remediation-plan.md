# Remediation Plan (2026-03-17)

This document tracks the repository hardening and stabilization work as phased delivery.
It is intended to make progress measurable and to keep implementation and validation in sync.

## Scope

- Align implementation with secure, maintainable production defaults.
- Remove critical correctness and security defects found in the initial audit.
- Make build, test, and runtime workflows deterministic for local and CI usage.
- Reconcile architecture/documentation drift.

## Delivery Principles

- Each phase has a clear acceptance checklist.
- Each phase is followed by explicit phase validation before proceeding.
- Avoid broad rewrites; prefer incremental, test-backed changes.
- Keep compatibility in mind for existing runtime behavior unless a fix requires a deliberate break.

## Phases

### Phase 1 - Baseline and Safety Setup

Objective:
- Create an execution framework for phased remediation with explicit gates.

Deliverables:
- This phase plan document.
- Phase status tracker.
- Scriptable phase validation entrypoint.

Acceptance:
- `docs/remediation-plan.md` exists and reflects current plan.
- `docs/phase-status.md` exists with initial state.
- `scripts/quality/phase_check.sh 1` runs and reports pass/fail with non-zero exit on failure.

### Phase 2 - Security Hardening

Objective:
- Close critical attack paths and auth exposure.

Primary targets:
- Admin route authorization.
- CORS policy tightening.
- Path traversal prevention in file-serving paths.
- XSS-safe rendering in frontend components.
- Remove/lock demo-only auth behavior from production pathways.

### Phase 3 - Core Correctness and Data Integrity

Objective:
- Fix logic defects and broken contracts affecting correctness.

Primary targets:
- Annotation field mismatch in chat/image flow.
- Feedback schema/API consistency.
- File-type contract alignment between frontend/backend.
- Vector index consistency on document deletion/dedupe flows.

### Phase 4 - Retrieval and Performance Stabilization

Objective:
- Improve retrieval determinism, relevance, and query efficiency.

Primary targets:
- Hybrid retrieval wiring consistency.
- O(N) attached-document chunk scan mitigation.
- BM25 lifecycle integration and index lifecycle checks.

### Phase 5 - Build, Runtime, and Environment Reliability

Objective:
- Make local and container workflows reliable and reproducible.

Primary targets:
- Makefile command portability (`python3`/venv-safe patterns).
- Dependency manifest alignment with lint/test commands.
- Docker/compose target and healthcheck consistency.
- Resolve fragile dependency import paths.

### Phase 6 - Test and Quality Gates

Objective:
- Ensure fixes are protected by automated checks.

Primary targets:
- Fill missing tests for security/correctness regressions.
- Stabilize pytest execution in clean environments.
- Add phase-appropriate lint/type/test gates.

### Phase 7 - Documentation and Architecture Alignment

Objective:
- Bring docs into full agreement with actual implementation.

Primary targets:
- README/CONTRIBUTING stack and run commands.
- Architecture docs and dev workflow correction.
- Remove stale Next.js/TS references if frontend remains static JS.

### Phase 8 - Final Hardening and Release Readiness

Objective:
- Final regression pass and production-readiness verification.

Primary targets:
- End-to-end smoke checks.
- Security/config sanity checklist.
- Release notes and handoff summary.

## Risks and Assumptions

- Existing local uncommitted changes may coexist with phased work.
- Some tests may initially fail due to environment or dependency drift; those failures are tracked and remediated in later phases.
- Runtime behavior differences between local and dockerized environments are expected until Phase 5 is complete.
