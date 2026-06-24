#!/usr/bin/env python3
"""
Bootstrap demo credentials and seed retrieval corpus from the golden dataset.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
DATASET_PATH = BACKEND_DIR / "data" / "golden_evaluation_dataset.jsonl"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.auth import auth_service
from app.core.database import async_session_factory
from app.services.bm25_index import bm25_index
from app.services.vector_store import vector_store_service


def _load_dataset() -> list[dict]:
    with DATASET_PATH.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


async def _bootstrap_admin() -> str | None:
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@clinicalgraph.ai").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or secrets.token_urlsafe(18)
    name = os.getenv("BOOTSTRAP_ADMIN_NAME", "Administrator").strip() or "Administrator"

    async with async_session_factory() as session:
        from app.models.user import User as DBUser
        from sqlalchemy import select
        
        result = await session.execute(select(DBUser).where(DBUser.email == email))
        user = result.scalar_one_or_none()
        if user:
            print(f"Admin already exists: {user.email}")
            return user.id

        try:
            user = await auth_service.bootstrap_admin_async(
                session,
                email=email,
                password=password,
                name=name,
            )
            await session.commit()
            print(f"Bootstrapped admin: {user.email}")
            if not os.getenv("BOOTSTRAP_ADMIN_PASSWORD"):
                print(f"Generated demo admin password: {password}")
            return user.id
        except Exception as exc:
            await session.rollback()
            print(f"Admin bootstrap failed: {exc}")
            
            result = await session.execute(select(DBUser).where(DBUser.email == email))
            user = result.scalar_one_or_none()
            if user:
                return user.id
            
            result = await session.execute(select(DBUser).where(DBUser.role == "admin").limit(1))
            user = result.scalar_one_or_none()
            return user.id if user else None


async def _seed_retrieval_corpus() -> None:
    rows = _load_dataset()
    backend = vector_store_service._get_backend()
    settings = getattr(backend, "settings", None)
    chunk_size = getattr(settings, "chunk_size", 512) if settings is not None else 512
    overlap = getattr(settings, "chunk_overlap", 64) if settings is not None else 64

    total_chunks = 0
    for index, row in enumerate(rows, start=1):
        contexts = row.get("context") or row.get("contexts") or []
        if isinstance(contexts, str):
            contexts = [contexts]
        import uuid
        for context_index, context_text in enumerate(contexts, start=1):
            doc_str = f"demo-golden-{index:02d}-{context_index:02d}"
            document_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_str))
            document_name = f"golden_case_{index:02d}_context_{context_index:02d}.txt"
            chunk_payloads = []
            for chunk_index, chunk in enumerate(backend.chunk_text(str(context_text), chunk_size=chunk_size, overlap=overlap)):
                chunk_payloads.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "chunk_index": chunk_index,
                        "text": chunk["text"],
                    }
                )
            # INSERT DOCUMENT TO DB FIRST TO AVOID FOREIGN KEY VIOLATION
            from app.models.document import Document
            from sqlalchemy import select
            import hashlib
            
            async with async_session_factory() as session:
                result = await session.execute(select(Document).where(Document.id == uuid.UUID(document_id)))
                db_doc = result.scalar_one_or_none()
                if not db_doc:
                    content_bytes = str(context_text).encode("utf-8")
                    content_hash = hashlib.sha256(content_bytes).hexdigest()
                    
                    # Delete any document with conflicting content hash to avoid unique constraint error
                    hash_result = await session.execute(select(Document).where(Document.content_hash == content_hash))
                    existing_hash_doc = hash_result.scalar_one_or_none()
                    if existing_hash_doc:
                        await session.delete(existing_hash_doc)
                        await session.flush()
                        
                    db_doc = Document(
                        id=uuid.UUID(document_id),
                        filename=document_name,
                        content_hash=content_hash,
                        file_size=len(content_bytes),
                        file_type="txt",
                        status="ready",
                        processing_stage="ready",
                        version_number=1,
                        is_latest_version=True,
                        duplicate_policy="reuse",
                        chunk_count=len(chunk_payloads),
                    )
                    session.add(db_doc)
                    await session.commit()

            vector_store_service.add_document(
                document_id=document_id,
                document_name=document_name,
                text=str(context_text),
                chunk_size=chunk_size,
                overlap=overlap,
                metadata={"seed": "demo", "source": "golden_evaluation_dataset"},
                chunks=chunk_payloads,
            )
            res = bm25_index.add_document(chunk_payloads, document_id, document_name)
            if hasattr(res, "__await__"):
                await res
            total_chunks += len(chunk_payloads)

    print(f"Seeded {len(rows)} golden cases into retrieval stores ({total_chunks} chunks).")


async def _seed_fhir_data(admin_user_id: str | None) -> None:
    SCRIPTS_DIR = REPO_ROOT / "scripts"
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))

    try:
        from generate_synthetic_clinical_data import generate_synthetic_data
        generate_synthetic_data(seed=42, output_dir=str(REPO_ROOT / "sample_data" / "synthetic"))
    except ImportError as e:
        print(f"Failed to import synthetic clinical data generator: {e}")
        return

    fhir_bundle_path = REPO_ROOT / "sample_data" / "synthetic" / "fhir_bundle.json"
    if not fhir_bundle_path.exists():
        print(f"FHIR bundle not found at {fhir_bundle_path}")
        return

    with open(fhir_bundle_path, "r", encoding="utf-8") as f:
        bundle_json = json.load(f)

    from app.services.fhir_ingestion import fhir_ingestion_service
    ingest_result = await fhir_ingestion_service.ingest_fhir_bundle(bundle_json, tenant_id=admin_user_id)
    print(f"Ingested FHIR bundle under tenant {admin_user_id}: {ingest_result}")


async def main() -> None:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")

    admin_user_id = await _bootstrap_admin()
    await _seed_retrieval_corpus()
    await _seed_fhir_data(admin_user_id)


if __name__ == "__main__":
    asyncio.run(main())
