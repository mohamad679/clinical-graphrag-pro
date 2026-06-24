# Phase Changelog (2026-03-17)

This changelog summarizes completed work by remediation phase.

## Phase 1 - Baseline and Safety Setup

- Added phased execution and tracking artifacts:
  - `docs/remediation-plan.md`
  - `docs/phase-status.md`
  - `scripts/quality/phase_check.sh` (initial phase gate)

## Phase 2 - Security Hardening

- Protected admin endpoints with `require_admin`.
- Tightened CORS parsing and runtime application.
- Added path traversal guards for image/file serving APIs.
- Hardened auth:
  - salted PBKDF2 password hashing
  - configurable demo auth behavior
- Reduced frontend XSS risk in chat/layout rendering paths.
- Added targeted security tests (`test_security.py`, auth/admin updates).

## Phase 3 - Core Correctness and Data Integrity

- Fixed image annotation field mismatch in chat context (`description` mapping).
- Added vector-store tombstoning on document deletion/dedupe.
- Added vector-store helpers for deleted-document filtering and chunk retrieval.
- Aligned feedback contract semantics (rating range/checks).
- Aligned frontend accepted file extensions with backend enforcement.
- Added correctness regression tests (`test_phase3_correctness.py`).

## Phase 4 - Retrieval and Performance Stabilization

- Integrated BM25 index lifecycle with ingestion and delete/dedupe flows.
- Corrected retrieval ranking behavior in query engine (vector/hybrid paths).
- Added bounded context assembly for attached-document retrieval.
- Added retrieval regression tests (`test_phase4_retrieval.py`).

## Phase 5 - Build, Runtime, and Environment Reliability

- Improved `Makefile` portability (`python3`/venv-safe behavior).
- Added missing quality dependencies (`ruff`, `pytest-cov`).
- Fixed Docker Compose frontend and healthcheck mismatches.
- Added reliability checks (`test_phase5_reliability.py`).

## Phase 6 - Test and Quality Gates

- Fixed pytest configuration format/defaults.
- Refactored fragile tests away from heavyweight `app.main` import paths.
- Gated heavy fine-tune tests behind `RUN_HEAVY_TESTS=true`.
- Added stable backend gate script:
  - `scripts/quality/backend_gate.sh`
- Added CI workflow:
  - `.github/workflows/backend-quality.yml`
- Added quality-gate regression tests (`test_phase6_quality_gate.py`).

## Phase 7 - Documentation and Architecture Alignment

- Rewrote primary docs to match actual architecture and runtime:
  - `README.md`
  - `CONTRIBUTING.md`
  - `docs/ARCHITECTURE.md`
  - `docs/API.md`
  - `frontend/README.md`
  - `docs/walkthrough.md`
  - `docs/implementation_plan.md`
- Added docs alignment tests (`test_phase7_docs_alignment.py`).

## Phase 8 - Final Hardening and Release Readiness

- Removed hardcoded external frontend API base; now runtime-resolved.
- Removed local absolute debug log path artifacts from documents API.
- Added release-readiness checklist and orchestration script:
  - `docs/release-readiness.md`
  - `scripts/quality/release_readiness.sh`
- Added final phase regression tests (`test_phase8_release_readiness.py`).
- Extended `scripts/quality/phase_check.sh` to include phase 8 end-to-end validation.

## Final Validation Snapshot

- `./scripts/quality/phase_check.sh 8` passed on 2026-03-17.
- Includes successful phase 2-7 regression sweep and backend quality gate pass.
