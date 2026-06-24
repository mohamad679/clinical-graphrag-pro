"""
Shared helpers for document pipeline stages, duplicate policy, and artifact cleanup.
"""

from __future__ import annotations

import hashlib
import inspect
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings
from app.services.bm25_index import bm25_index
from app.services.graph import temporal_graph_service
from app.services.storage import storage_service
from app.services.vector_store import vector_store_service

if TYPE_CHECKING:
    from app.models.document import Document


DOCUMENT_PIPELINE_STAGES = [
    "uploaded",
    "validated",
    "extracted",
    "chunked",
    "embedded",
    "indexed_lexical",
    "entities_extracted",
    "graph_ingested",
    "ready",
    "failed",
]
ALLOWED_DUPLICATE_POLICIES = {"reuse", "version", "reject", "overwrite"}
PIPELINE_PROGRESS = {
    "uploaded": 5,
    "validated": 12,
    "extracted": 28,
    "chunked": 45,
    "embedded": 65,
    "indexed_lexical": 80,
    "entities_extracted": 90,
    "graph_ingested": 96,
    "ready": 100,
    "failed": 100,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_duplicate_policy(policy: str | None, default: str = "reuse") -> str:
    normalized = (policy or default or "reuse").strip().lower()
    if normalized not in ALLOWED_DUPLICATE_POLICIES:
        allowed = ", ".join(sorted(ALLOWED_DUPLICATE_POLICIES))
        raise ValueError(f"duplicate_policy must be one of: {allowed}")
    return normalized


def build_scoped_content_hash(user_id: str, filename: str, raw_checksum: str) -> str:
    scoped = f"{user_id}:{Path(filename).name.lower()}:{raw_checksum}"
    return hashlib.sha256(scoped.encode("utf-8")).hexdigest()


def build_initial_document_metadata(
    *,
    filename: str,
    duplicate_policy: str,
    raw_checksum: str,
    version_group_id: str,
    version_number: int,
    previous_version_id: str | None = None,
    existing: dict | None = None,
) -> dict[str, Any]:
    metadata = dict(existing or {})
    metadata["raw_checksum"] = raw_checksum
    metadata["version_group_id"] = version_group_id
    metadata["version_number"] = version_number
    metadata["previous_version_id"] = previous_version_id
    metadata["duplicate_policy"] = duplicate_policy
    metadata["source_filename"] = filename
    metadata["pipeline"] = {
        "current_stage": "uploaded",
        "trace": [],
        "last_updated_at": _utcnow().isoformat(),
    }
    return record_pipeline_stage(
        metadata,
        "uploaded",
        state="completed",
        details={
            "filename": filename,
            "duplicate_policy": duplicate_policy,
            "version_number": version_number,
        },
    )


def record_pipeline_stage(
    metadata: dict[str, Any] | None,
    stage: str,
    *,
    state: str,
    details: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    if stage not in DOCUMENT_PIPELINE_STAGES:
        raise ValueError(f"Unknown document stage: {stage}")

    payload = dict(metadata or {})
    pipeline = dict(payload.get("pipeline") or {})
    trace = list(pipeline.get("trace") or [])
    event = {
        "stage": stage,
        "state": state,
        "timestamp": _utcnow().isoformat(),
        "details": details or {},
    }
    if error:
        event["error"] = error
    trace.append(event)

    pipeline["current_stage"] = stage
    pipeline["trace"] = trace
    pipeline["last_updated_at"] = event["timestamp"]
    payload["pipeline"] = pipeline
    return payload


def current_stage(metadata: dict[str, Any] | None, fallback: str = "uploaded") -> str:
    pipeline = (metadata or {}).get("pipeline") or {}
    stage = pipeline.get("current_stage")
    if isinstance(stage, str) and stage:
        return stage
    return fallback


def pipeline_trace(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    pipeline = (metadata or {}).get("pipeline") or {}
    trace = pipeline.get("trace") or []
    return list(trace) if isinstance(trace, list) else []


def coarse_status_for_stage(stage: str, state: str) -> str:
    if stage == "uploaded" and state != "failed":
        return "queued"
    if stage == "ready" and state == "completed":
        return "ready"
    if stage == "failed" or state == "failed":
        return "error"
    return "processing"


def progress_for_stage(stage: str, state: str) -> int:
    if stage == "failed" or state == "failed":
        return 100
    return PIPELINE_PROGRESS.get(stage, 0)


async def deindex_document_artifacts(document_id: str) -> dict[str, int]:
    chunks_removed = vector_store_service.mark_document_deleted(str(document_id))
    bm25_removed = bm25_index.mark_document_deleted(str(document_id))
    if inspect.isawaitable(bm25_removed):
        bm25_removed = await bm25_removed
    graph_removed = await temporal_graph_service.delete_document_artifacts(str(document_id))
    return {
        "chunks_removed": int(chunks_removed or 0),
        "bm25_removed": int(bm25_removed or 0),
        "graph_removed": int(graph_removed or 0),
    }


async def purge_document_artifacts(document: Document) -> dict[str, int | bool]:
    settings = get_settings()
    file_removed = False
    if document.storage_asset is not None:
        await storage_service.delete(
            bucket=document.storage_asset.bucket,
            object_key=document.storage_asset.object_key,
            storage_metadata=document.storage_asset.storage_metadata,
        )
        document.storage_asset.deleted_at = document.storage_asset.deleted_at or _utcnow()
        file_removed = True
    else:
        suffixes = {((document.metadata_ or {}).get("original_suffix")) or f".{document.file_type}", f".{document.file_type}"}
        for suffix in suffixes:
            local_path = settings.upload_dir / f"{document.id}{suffix}"
            if local_path.exists():
                local_path.unlink()
                file_removed = True

    deindex_result = await deindex_document_artifacts(str(document.id))
    return {"file_removed": file_removed, **deindex_result}
