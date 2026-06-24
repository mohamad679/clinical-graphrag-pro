# Security Policy

## Security Model Overview

Clinical GraphRAG Pro uses a database-backed authentication model built around signed JWT access tokens, refresh tokens, durable session records, and explicit role-based authorization checks in the FastAPI layer. The current role hierarchy is `viewer`, `nurse`, `physician`, and `admin`, and endpoints are protected through dependency-based role enforcement rather than ad hoc request branching. Security-relevant actions such as authentication events, admin operations, and image/document workflows are written to an audit trail so request outcomes remain attributable after the fact.

### Retrieval Scoping & Fail-Closed Enforcement

The retrieval subsystem is engineered to prevent unauthorized access across different users, tenants, or patients (cross-tenant data leakage):
- **Unified Gateway Control**: All RAG, Agent tool, and temporal graph queries route through the unified `QueryEngine.query` gateway, ensuring uniform security enforcement.
- **Fail-Closed Validation**: If a query is initiated without supplying context boundaries (`user_id`, `tenant_id`, `patient_id`, `organization_id`, or `owner`), the gateway will immediately fail closed and raise a `ValueError`.
- **Pre & Post Filtering**: The storage layers (FAISS, Qdrant, and PostgreSQL JSONB BM25 Index) apply strict pre-filtering and post-filtering on metadata fields to ensure only records belonging to the matching tenant/patient boundaries are evaluated.

This is a portfolio and research system with several production-style controls, but it should not be confused with a complete HIPAA-ready deployment. The repository demonstrates durable sessions, revocation, audit logging, scoped retrieval, and defensive file-handling patterns; it does not claim to solve the full set of organizational, regulatory, or infrastructure controls required for real PHI processing in production.

This project is for educational and portfolio demonstration purposes only. It is not a medical device, not clinically validated, and must not be used for diagnosis, treatment, triage, medication decisions, or real patient care. All outputs require review by qualified clinical professionals.

## Scope

| Area | In Scope for This Demo Project | Not in Scope for This Demo Project |
| --- | --- | --- |
| Authentication | JWT signing, refresh tokens, RBAC, session persistence, session revocation | Enterprise SSO, SCIM provisioning, hardware-backed auth, MFA rollout policy |
| Authorization | Role checks and user/tenant scoping in API and retrieval paths | Formal ABAC policy engine, organization-wide identity governance |
| Auditability | Request audit logs, auth events, workflow/job metadata | SIEM integration, immutable external audit archive, regulatory reporting workflow |
| Data handling | File validation, DICOM PHI scrubbing path, upload/storage abstractions | Full HIPAA administrative safeguards, BAA management, production PHI governance program |
| Infrastructure | Dockerized deployment, CI quality gates, staged release-readiness scripts | WAF, HSM/KMS-backed key rotation, managed secrets platform, zero-trust network architecture |
| Monitoring | Health checks, metrics, structured logging, evaluation gates | 24/7 SOC operations, incident response staffing, enterprise threat detection platform |

## Generating a Secure JWT_SECRET

Use a cryptographically strong secret with at least 32 characters. Two practical options are:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

```bash
openssl rand -base64 48
```

Set the generated value in your environment before running the backend:

```bash
export JWT_SECRET='CHANGE_ME_WITH_A_REAL_SECRET'
```

Never commit live secrets to the repository, and do not reuse a JWT secret across unrelated environments.

## Research / Portfolio Disclaimer

This repository is a research and portfolio project. It is not suitable for production PHI handling without additional HIPAA-aligned controls such as secure key management, formal access reviews, backup and disaster-recovery procedures, managed secrets rotation, network hardening, logging retention policy, incident response processes, and legal/compliance review.

If you intend to process real patient data, treat this repository as a starting point for engineering discussion, not as a deployment-ready compliance baseline.

## Production Configuration Notes

- Use `.env.example` only as a template; do not commit `.env` files.
- Set a unique `JWT_SECRET` with at least 32 characters.
- If a real key is ever shared through a ZIP or external tool, rotate it immediately even if it was never committed to Git.
- Do not use default PostgreSQL, Redis, Neo4j, or Grafana credentials outside local development.
- Keep PostgreSQL, Redis, Neo4j, and Qdrant on private networks; expose only nginx or an explicitly secured API gateway.
- `APP_ENV=production` enables stricter startup validation for common unsafe defaults, but it is not a substitute for managed infrastructure hardening.
- Treat uploaded documents, graph notes, tool output, image analysis text, evaluator input, and model output as untrusted text. The backend formats retrieved evidence as quoted JSONL data and validates citations before streaming.
- Set `OBSERVABILITY_MODE=PRODUCTION_METADATA_ONLY` for production-like environments so logs preserve request IDs, stages, latency, model identifiers, counts, and validation statuses without storing raw patient text, document chunks, prompts, full answers, or tool output.

See [THREAT_MODEL.md](THREAT_MODEL.md) and [docs/HARDENING_VERIFICATION_REPORT.md](docs/HARDENING_VERIFICATION_REPORT.md) for current controls and residual risks.

## Reporting a Vulnerability

If you discover a security issue, please do not open a public GitHub issue with exploit details. Instead:

1. Prepare a concise report describing the affected component, impact, reproduction steps, and any suggested mitigation.
2. Send the report privately to the repository maintainer through a private channel or GitHub security advisory workflow, if enabled.
3. Allow reasonable time for triage and remediation before public disclosure.

Reports that clearly identify the vulnerable code path, expected vs. observed behavior, and any environment assumptions are the most useful.
