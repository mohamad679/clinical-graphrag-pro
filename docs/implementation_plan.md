# Implementation Plan (Canonical)

This repository follows the phased remediation plan defined in:
- `docs/remediation-plan.md`
- `docs/phase-status.md`

## Current Canonical Execution Model

Each phase follows:
1. Implement scoped changes.
2. Wait for approval.
3. Run `scripts/quality/phase_check.sh <phase>`.
4. Continue only after passing checks.

## Quality Gate Entry Points

- Per-phase checks:
  - `./scripts/quality/phase_check.sh 1`
  - `./scripts/quality/phase_check.sh 2`
  - ...
- Stable backend gate:
  - `bash scripts/quality/backend_gate.sh`

## Notes

- Older planning text referencing `frontend/src/...`, Next.js pages/components, and outdated roadmap tasks has been superseded.
- The current frontend runtime is static and served from `frontend/public`.
- Keep this file synchronized with `docs/remediation-plan.md` if process changes.
