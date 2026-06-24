# Hardening Verification Report

Last verified: 2026-06-06

## Architecture Summary

Clinical GraphRAG Pro is a FastAPI portfolio project with PostgreSQL-backed auth/session/job state, Redis/Celery background work, FAISS dense retrieval, BM25 sparse retrieval, optional reranking, a temporal graph layer, static Web Components frontend, and SSE chat/agent streams.

This repository is a synthetic-data demonstration. It is not clinically validated, not intended for real patient data, not HIPAA-compliant or GDPR-compliant by default, not a medical device, and not production-ready without independent review.

## Security Controls

- JWT/RBAC endpoint protection and scoped user/tenant retrieval filters.
- Fail-closed retrieval gateway when isolation scope is missing.
- Citation marker validation and weak-support warnings for citation laundering.
- Prompt-injection containment through `UntrustedText` and JSONL evidence formatting.
- Tool output treated as untrusted data in synthesis/verification prompts.
- Durable worker dispatch for long-running jobs such as fine-tuning.
- WebSocket chat uses short-lived, single-use tickets issued by `/api/auth/ws-ticket`; long-lived access tokens are not accepted in WebSocket query strings.
- Recursive log redaction with explicit observability modes.
- Magic-byte upload validation, image size/pixel limits, metadata stripping, and DICOM manual-review requirements.

## Safe-Streaming Invariant

Chat and RAG streaming emit final answer tokens only after the response has been generated and grounding/citation policy has run. Unsafe pre-validation streaming modes are rejected by configuration and runtime checks.

Normal browser responses receive `public` trace metadata only: latency, model identifiers, citation IDs, document IDs, counts, validation flags, and state names. Raw prompts, retrieved chunk text, `final_context`, tool output, and patient text are not returned in public traces. Admin-only `debug_redacted` traces are available only in non-production debug mode. `internal_full` traces are not returned to browser clients and are disabled by default.

## Retrieval Benchmark Summary

Latest versioned artifact: `results/retrieval_evaluation_results_20260605T223340Z.json`

Synthetic suite: `backend/data/synthetic_clinical_qa_180.jsonl`

Measured methods: dense FAISS, sparse BM25, hybrid FAISS+BM25+RRF, hybrid plus reranking.

The latest run shows BM25 is functional and has non-zero candidates. Hybrid and reranked hybrid matched dense/sparse quality metrics on the synthetic suite and added latency. Do not claim hybrid improvement unless a newer measured artifact supports it.

## Fine-Tuning Status

Fine-tuning is disabled by default. The code now exposes a durable control plane and a real PEFT/LoRA training backend path, but local verification did not run GPU training. Jobs report explicit unavailable states when GPU or dependencies are missing. Deployment requires adapter reload verification, evaluation gate approval, and inference integration verification.

## Red-Team Coverage

Regression tests cover prompt injection in uploaded/retrieved text, fake system prompts, malicious tool output, graph/evidence citation issues, citation laundering, fabricated citations, conflicting or missing evidence, cross-tenant retrieval, guessed image filenames, unauthorized evaluation history, unauthenticated access, non-admin fine-tuning, spoofed forwarding headers, Redis outage behavior, DICOM metadata, DICOM burned-in-text limitations, multi-frame DICOM rejection, oversized/path traversal media boundaries, unsafe streaming, evaluator prompt-injection paths, and trace/log redaction.

Primary files:

- `backend/tests/test_adversarial_safety.py`
- `backend/tests/test_safety_grounding.py`
- `backend/tests/test_security_hardening_scope.py`
- `backend/tests/test_final_hardening_gate.py`

## DICOM Limitations

DICOM uploads are disabled by default. If enabled, known PHI metadata tags are scrubbed and pixel data is converted to PNG. Multi-frame DICOM is rejected. Burned-in text detection is `manual-review-only`; the code does not perform OCR-based identifier removal and does not claim complete de-identification. DICOM-derived images require manual review before downstream use.

## Logging Modes

- `LOCAL_SYNTHETIC_DEBUG`: preserves useful local synthetic debugging while still redacting known secrets.
- `STAGING_REDACTED`: redacts secrets and sensitive path-like fields.
- `PRODUCTION_METADATA_ONLY`: stores safe metadata such as request IDs, tenant-safe identifiers, stage, latency, model identifier, retrieval counts, validation status, abstention status, and error category while redacting raw patient text, chunks, prompts, tool output, answers, and sensitive paths.

## CI Commands

Local focused hardening checks:

```bash
backend/.venv/bin/python -m pytest backend/tests/test_final_hardening_gate.py --no-cov
```

Full backend regression:

```bash
backend/.venv/bin/python -m pytest backend/tests --no-cov
```

Fresh environment verification:

```bash
bash scripts/quality/fresh_env_verify.sh
```

CI also runs lint, optional type checks when configured, migration graph validation, unit/integration tests with line and branch coverage, security tests/scans, red-team regression tests, retrieval benchmark smoke tests, documentation checks, tracked-file secret scanning, and dependency vulnerability scanning where tooling is available.
