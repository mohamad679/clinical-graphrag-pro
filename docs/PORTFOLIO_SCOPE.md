# Portfolio Release Scope

This repository is scoped as a Senior Applied AI Engineer portfolio project. It is not a clinical product, HIPAA compliance program, medical device, or validated decision-support system.

## Required For Current Portfolio Release

- Clean release artifact without secrets, local databases, uploads, caches, or virtualenv contents.
- No committed secrets.
- Passing CI gates, including mandatory Pyright type checking.
- WebSocket ticket authentication.
- Safe public traces and production metadata-only observability.
- Safe error envelopes.
- Fact-level graph provenance.
- Structured grounding checks.
- Synthetic retrieval benchmark v2.
- Zero measured cross-tenant leakage in benchmark v2.
- Enforced retrieval benchmark v2 gates for duplicate ratio, leakage, default-mode Recall@5, answerable top-5 evidence misses, category metrics, dataset version, and commit hash.
- Hybrid RRF enabled as the default measured retrieval mode; cross-encoder reranking remains configurable but disabled by default because its latest synthetic v2 latency cost was not justified for the portfolio release.
- Real Redis distributed cache when `CACHE_BACKEND=redis`, with documented production bypass and development/offline in-memory fallback on outage.
- Argon2id password hashes for new passwords, with PBKDF2 and temporary SHA-256 migration on successful login.
- Accurate documentation of runtime behavior and limitations.

## Optional Future Roadmap

- Kubernetes deployment.
- Multi-region deployment.
- HIPAA compliance program.
- FDA pathway or medical-device readiness.
- Real patient data.
- Prospective clinical validation.
- Enterprise EHR integration.
- Large-scale fine-tuning.
- Transactional outbox for Neo4j if stricter mirror guarantees are needed.
- Million-scale load testing.
- SBOM generation and artifact signing.

These roadmap items are not blockers for the current portfolio release unless a future release explicitly expands scope.
