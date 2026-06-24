from __future__ import annotations

import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine


pytestmark = pytest.mark.asyncio


def _postgres_test_url() -> str | None:
    return os.environ.get("POSTGRES_FTS_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _postgres_available() -> bool:
    try:
        with socket.create_connection(("localhost", 5432), timeout=1.0):
            return True
    except OSError:
        return False


async def test_postgres_document_chunk_fts_migration_and_scope_filters():
    if os.environ.get("RUN_POSTGRES_FTS_MIGRATION_TEST") != "true":
        pytest.skip("PostgreSQL FTS migration integration test is opt-in.")

    database_url = _postgres_test_url()
    if not database_url or "postgresql" not in database_url:
        if os.environ.get("RUN_POSTGRES_FTS_MIGRATION_TEST", "").lower() == "true":
            pytest.fail("PostgreSQL database URL is required for explicit FTS migration verification.")
        pytest.skip("PostgreSQL database URL is required for FTS migration integration test.")
    if not _postgres_available():
        if os.environ.get("RUN_POSTGRES_FTS_MIGRATION_TEST", "").lower() == "true":
            pytest.fail("PostgreSQL service is required but unavailable.")
        pytest.skip("PostgreSQL service is not available on localhost:5432.")

    backend_dir = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend_dir, env=env, check=True)

    engine = create_async_engine(database_url)
    document_id = str(uuid.uuid4())
    chunk_row_id = str(uuid.uuid4())
    chunk_id = f"fts-test-{uuid.uuid4()}"
    tenant_id = "tenant-fts-ci"
    patient_id = "patient-fts-ci"

    try:
        async with engine.begin() as conn:
            column = (
                await conn.exec_driver_sql(
                    """
                    SELECT udt_name
                    FROM information_schema.columns
                    WHERE table_name = 'document_chunks' AND column_name = 'search_vector'
                    """
                )
            ).scalar_one()
            assert column == "tsvector"

            index_definition = (
                await conn.exec_driver_sql(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE tablename = 'document_chunks'
                      AND indexname = 'ix_document_chunks_search_vector_gin'
                    """
                )
            ).scalar_one()
            assert "using gin" in index_definition.lower()

            await conn.exec_driver_sql(
                """
                INSERT INTO documents (
                    id, filename, content_hash, file_size, file_type, chunk_count, status,
                    processing_progress, metadata, extracted_entities, uploaded_at,
                    version_number, is_latest_version, duplicate_policy, processing_stage
                )
                VALUES (
                    %(document_id)s::uuid, 'fts-test.txt', %(content_hash)s, 128, 'txt', 1, 'ready',
                    100, '{"tenant_id":"tenant-fts-ci","patient_id":"patient-fts-ci"}'::json,
                    '[]'::json, now(), 1, true, 'reuse', 'ready'
                )
                """,
                {"document_id": document_id, "content_hash": chunk_id.replace("-", "")[:64]},
            )
            await conn.exec_driver_sql(
                """
                INSERT INTO document_chunks (
                    id, document_id, user_id, chunk_id, chunk_index, chunk_text,
                    normalized_text, token_count, metadata, created_at
                )
                VALUES (
                    %(chunk_row_id)s::uuid, %(document_id)s::uuid, 'user-fts-ci', %(chunk_id)s, 0,
                    'Cefazolin was continued for methicillin susceptible Staphylococcus aureus bacteremia.',
                    'cefazolin continued methicillin susceptible staphylococcus aureus bacteremia',
                    8, '{"tenant_id":"tenant-fts-ci","patient_id":"patient-fts-ci"}'::json, now()
                )
                """,
                {"chunk_row_id": chunk_row_id, "document_id": document_id, "chunk_id": chunk_id},
            )

            match = (
                await conn.exec_driver_sql(
                    """
                    SELECT chunk_id
                    FROM document_chunks
                    WHERE search_vector @@ plainto_tsquery('english', 'cefazolin bacteremia')
                      AND metadata->>'tenant_id' = %(tenant_id)s
                      AND metadata->>'patient_id' = %(patient_id)s
                    """,
                    {"tenant_id": tenant_id, "patient_id": patient_id},
                )
            ).scalar_one()
            assert match == chunk_id

            blocked = (
                await conn.exec_driver_sql(
                    """
                    SELECT count(*)
                    FROM document_chunks
                    WHERE search_vector @@ plainto_tsquery('english', 'cefazolin bacteremia')
                      AND metadata->>'tenant_id' = 'other-tenant'
                      AND metadata->>'patient_id' = %(patient_id)s
                    """,
                    {"patient_id": patient_id},
                )
            ).scalar_one()
            assert blocked == 0

            await conn.exec_driver_sql("SET enable_seqscan = off")
            plan_rows = (
                await conn.exec_driver_sql(
                    """
                    EXPLAIN
                    SELECT chunk_id
                    FROM document_chunks
                    WHERE search_vector @@ plainto_tsquery('english', 'cefazolin bacteremia')
                      AND metadata->>'tenant_id' = %(tenant_id)s
                      AND metadata->>'patient_id' = %(patient_id)s
                    """,
                    {"tenant_id": tenant_id, "patient_id": patient_id},
                )
            ).all()
            plan_text = "\n".join(row[0] for row in plan_rows)
            assert "ix_document_chunks_search_vector_gin" in plan_text
    finally:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("DELETE FROM documents WHERE id = %(document_id)s::uuid", {"document_id": document_id})
        await engine.dispose()
