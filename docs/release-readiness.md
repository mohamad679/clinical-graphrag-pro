# Release Readiness Checklist

This checklist is the operational hardening summary for monitoring, deployability, recovery, and rollback.

## Observability

- Request logs now carry `request_id`, `trace_id`, endpoint, latency, status code, and request-scoped identifiers where available.
- Trace spans are emitted for API orchestration, DB work, Redis operations, Celery execution, LLM calls, and vector search.
- Admin metrics expose dashboard rollups for chat latency, retrieval latency, LLM/document failure rate, image analysis success rate, and worker queue depth.
- Detailed health includes migration state, broker health, vector/graph dependencies, and queue depth.

## Release Gates

- `scripts/quality/migration_gate.sh` validates the Alembic graph and can enforce a live DB migration check with `RUN_LIVE_MIGRATION_CHECK=true`.
- `scripts/quality/backend_gate.sh` runs compile, lint, stable backend tests, and the internal evaluation gate.
- `scripts/quality/integration_gate.sh` runs smoke-style integration tests across core endpoints and durable document flow.
- `scripts/quality/security_gate.sh` runs secrets checks, security-focused pytest coverage, and optional `bandit` / `pip-audit` scans.
- `scripts/quality/release_readiness.sh` orchestrates the full release gate and validates both production and staging compose manifests.

## Staging

- `docker-compose.staging.yml` provides a production-like staging override with broker-required background jobs, Qdrant, and Neo4j enabled.
- `backend/scripts/staging_smoke.py` executes the real staging flow: login, document upload/process, chat, image upload/analyze, and graph search.
- `scripts/quality/staging_smoke.sh` wraps the smoke test for CI/manual release use with `STAGING_BASE_URL`, `STAGING_ADMIN_EMAIL`, and `STAGING_ADMIN_PASSWORD`.

## Backup And Restore

- `scripts/ops/backup_postgres.sh` captures PostgreSQL backups with `pg_dump`.
- `scripts/ops/restore_postgres.sh` restores a captured PostgreSQL backup with `pg_restore`.
- `scripts/ops/backup_object_storage.sh` mirrors S3/MinIO-style object storage with `aws` or `mc`.
- `scripts/ops/backup_vector_graph.sh` captures Qdrant snapshots and Neo4j dumps when the required tooling is available.
- `scripts/ops/backup_restore_drill.sh` orchestrates a backup drill and can run a restore test with `RUN_RESTORE_TEST=true`.

## Rollback

- Rollback starts with a fresh backup capture, then redeploying the previous known-good application version and restoring data stores only if required.
- The manual release workflow in `.github/workflows/backend-quality.yml` is the intended pre-production checkpoint before promotion.
- If a deployment fails after release, re-run `scripts/quality/release_readiness.sh` against staging, confirm the last good build, and restore from the latest validated backups if state corruption is suspected.

## Recommended Commands

```bash
./scripts/quality/phase_check.sh 8
```

```bash
bash scripts/quality/release_readiness.sh
```

For a full manual release drill, set:

```bash
RUN_STAGING_SMOKE=true RUN_BACKUP_DRILL=true RUN_RESTORE_TEST=true bash scripts/quality/release_readiness.sh
```
