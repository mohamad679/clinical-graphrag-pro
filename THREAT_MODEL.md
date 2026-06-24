# Threat Model

## Scope

This threat model covers the active development repository for Clinical GraphRAG Pro. The system is a portfolio and synthetic-data demonstration, not a production clinical platform.

## Assets

- User/session identity and JWT-derived claims.
- Tenant, user, patient, document, image, and job identifiers.
- Uploaded document and image content in local development storage.
- Retrieval indexes and benchmark artifacts.
- LLM prompts, retrieved evidence, tool output, traces, and evaluation results.
- Local environment files and secrets, which must not be logged or committed.

## Trust Boundaries

- Browser to FastAPI API.
- API to PostgreSQL, Redis/Celery, vector store, BM25 index, graph service, and optional LLM providers.
- Uploaded files, retrieved chunks, graph labels/notes, image analysis text, tool output, evaluator input, and model output are all untrusted data.
- CI and local scripts must not depend on real external API keys for normal success.

## Key Threats and Controls

| Threat | Current Control | Residual Risk |
| --- | --- | --- |
| Prompt injection in documents, graph text, tool output, evaluator input | `UntrustedText` representation, JSONL evidence formatting, explicit prompts, citation validation, red-team tests | Prompt wording is not a complete defense; deterministic checks are heuristic |
| Citation laundering or fabricated citations | Citation marker validation, invented-citation rejection, weak support warnings | Keyword support is not full entailment |
| Cross-tenant retrieval | `RetrievalScope`, fail-closed query gateway, dense/sparse filtering tests | Requires continued review when adding new stores/tools |
| Unsafe streaming | Full answer generated and validated before token streaming | Any new streaming path must preserve this invariant |
| Secret/log leakage | Recursive redaction and `PRODUCTION_METADATA_ONLY` mode | Local debug mode can retain synthetic raw text by design |
| Uploaded file abuse | Magic-byte validation, size/pixel limits, metadata stripping, path traversal checks | DICOM burned-in text detection is manual-review-only |
| DICOM PHI leakage | Known metadata tag scrubbing and DICOM-derived manual review requirement | No OCR pixel-text removal; not complete de-identification |
| Background job abuse | Durable worker dispatch for long jobs, no request-process fine-tune training | Worker environment still needs production hardening |
| Dependency and CI drift | Python 3.12 declaration, pinned backend requirements, CI gates, fresh-env script | Vulnerability scans depend on current advisory databases |

## Non-Claims

This repository does not claim HIPAA compliance, GDPR compliance, production readiness, clinical validation, autonomous medical reasoning, or complete PHI de-identification.
