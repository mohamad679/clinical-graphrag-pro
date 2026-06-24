"""
Document upload and management API endpoints.
Queued processing with PostgreSQL metadata and background indexing.
"""

import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from uuid import UUID

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.auth import User, require_role
from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.core.database import get_db
from app.core.metrics import mark_document_upload
from app.models.document import Document
from app.models.persistence import StoredAsset
from app.services.document_pipeline import (
    build_initial_document_metadata,
    build_scoped_content_hash,
    current_stage,
    normalize_duplicate_policy,
    pipeline_trace,
    progress_for_stage,
    purge_document_artifacts,
    record_pipeline_stage,
)
from app.services.job_state import job_state_service
from app.services.storage import storage_service
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
)
from app.worker import dispatch_document_processing

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/documents",
    tags=["Documents"],
    dependencies=[Depends(require_role("physician"))],
)

settings = get_settings()
ALLOWED_DOCUMENT_SUFFIXES = (".pdf", ".txt", ".md", ".csv")

def _document_to_response(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        file_size=document.file_size,
        chunk_count=document.chunk_count,
        status=document.status,
        stage=document.processing_stage,
        processing_progress=document.processing_progress,
        uploaded_at=document.uploaded_at,
        processed_at=document.processed_at,
        error_message=document.error_message,
        extracted_entities=document.extracted_entities,
        version_number=document.version_number,
        is_latest_version=document.is_latest_version,
        duplicate_policy=document.duplicate_policy,
        pipeline_trace=pipeline_trace(document.metadata_),
    )


async def _promote_previous_version(
    db: AsyncSession,
    document: Document,
    *,
    requeue_index: bool,
) -> Document | None:
    if not document.version_group_id:
        return None

    previous_result = await db.execute(
        select(Document)
        .where(
            Document.version_group_id == document.version_group_id,
            Document.user_id == document.user_id,
            Document.id != document.id,
            Document.version_number < document.version_number,
        )
        .order_by(Document.version_number.desc())
        .limit(1)
    )
    previous = previous_result.scalar_one_or_none()
    if previous is None:
        return None

    previous.is_latest_version = True
    previous.superseded_at = None
    if requeue_index:
        previous.status = "queued"
        previous.processing_stage = current_stage(previous.metadata_)
        previous.processing_progress = progress_for_stage(previous.processing_stage, "completed")
    return previous


async def _ensure_processing_job(db: AsyncSession, document: Document) -> str:
    if document.processing_job_id is not None:
        return str(document.processing_job_id)

    job = await job_state_service.create_job(
        db,
        job_type="document_processing",
        entity_type="document",
        entity_id=str(document.id),
        created_by_user_id=document.user_id,
        payload={"filename": document.filename, "duplicate_policy": document.duplicate_policy},
        metadata={"current_stage": document.processing_stage},
        dedupe_active=False,
    )
    document.processing_job_id = job.id
    await db.flush()
    return str(job.id)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    http_request: Request,
    file: UploadFile = File(...),
    duplicate_policy: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """
    Upload a document and queue it for background chunking/embedding.
    """
    try:
        normalized_duplicate_policy = normalize_duplicate_policy(
            duplicate_policy,
            settings.document_duplicate_policy,
        )
        normalized_filename = Path(file.filename or "unknown").name

        # Validate file type
        suffix = Path(normalized_filename).suffix.lower()
        if suffix not in ALLOWED_DOCUMENT_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {suffix}. Allowed: {', '.join(ALLOWED_DOCUMENT_SUFFIXES)}",
            )

        # Read file content
        content_bytes = await file.read()

        # Check size
        max_size = settings.max_upload_size_mb * 1024 * 1024
        if len(content_bytes) > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Max size: {settings.max_upload_size_mb}MB",
            )

        # Compute hash for deduplication
        raw_checksum = hashlib.sha256(content_bytes).hexdigest()
        content_hash = build_scoped_content_hash(user.id, normalized_filename, raw_checksum)

        latest_result = await db.execute(
            select(Document)
            .options(selectinload(Document.storage_asset))
            .where(
                Document.user_id == user.id,
                Document.filename == normalized_filename,
                Document.is_latest_version.is_(True),
            )
            .order_by(Document.version_number.desc())
            .limit(1)
        )
        latest_doc = latest_result.scalar_one_or_none()
        if latest_doc and latest_doc.content_hash == content_hash:
            if normalized_duplicate_policy == "reject":
                raise HTTPException(
                    status_code=409,
                    detail="An identical document version already exists for this filename.",
                )
            return DocumentUploadResponse(
                id=str(latest_doc.id),
                filename=latest_doc.filename,
                status=latest_doc.status,
                stage=latest_doc.processing_stage,
                processing_progress=latest_doc.processing_progress,
                chunk_count=latest_doc.chunk_count,
                version_number=latest_doc.version_number,
                message="Identical document content already exists; reused the current version.",
            )

        doc_uuid = uuid4()
        doc_id = str(doc_uuid)
        version_group_id = str(latest_doc.version_group_id or latest_doc.id) if latest_doc else doc_id
        version_number = (latest_doc.version_number + 1) if latest_doc else 1
        previous_version_id = str(latest_doc.id) if latest_doc and latest_doc.content_hash != content_hash else None

        stored = await storage_service.store_bytes(
            category="documents",
            filename=normalized_filename,
            content=content_bytes,
            content_type=file.content_type or "application/octet-stream",
        )
        asset = StoredAsset(
            owner_user_id=user.id,
            category="document",
            provider=stored.provider,
            bucket=stored.bucket,
            object_key=stored.object_key,
            original_filename=stored.original_filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            checksum=stored.checksum,
            encryption_status=stored.encryption_status,
            storage_metadata=stored.storage_metadata,
        )
        db.add(asset)
        await db.flush()

        job = await job_state_service.create_job(
            db,
            job_type="document_processing",
            entity_type="document",
            entity_id=doc_id,
            created_by_user_id=user.id,
            payload={"filename": normalized_filename, "duplicate_policy": normalized_duplicate_policy},
            metadata={"current_stage": "uploaded"},
        )

        if latest_doc and latest_doc.content_hash != content_hash:
            latest_doc.is_latest_version = False

        # Persist metadata
        doc = Document(
            id=doc_uuid,
            user_id=user.id,
            previous_version_id=UUID(previous_version_id) if previous_version_id else None,
            storage_asset_id=asset.id,
            processing_job_id=job.id,
            filename=normalized_filename,
            content_hash=content_hash,
            version_group_id=version_group_id,
            version_number=version_number,
            is_latest_version=True,
            duplicate_policy=normalized_duplicate_policy,
            file_size=len(content_bytes),
            file_type=suffix.lstrip("."),
            content_type=stored.content_type,
            chunk_count=0,
            status="queued",
            processing_stage="uploaded",
            processing_progress=0,
            metadata_=build_initial_document_metadata(
                filename=normalized_filename,
                duplicate_policy=normalized_duplicate_policy,
                raw_checksum=raw_checksum,
                version_group_id=version_group_id,
                version_number=version_number,
                previous_version_id=previous_version_id,
                existing={"original_suffix": suffix},
            ),
        )
        db.add(doc)
        await db.flush()
        await db.commit()
        if http_request is not None:
            http_request.state.document_id = doc_id
            http_request.state.job_id = str(job.id)
            http_request.state.task_type = "document_processing"

        try:
            await dispatch_document_processing(doc_id, job_id=str(job.id))
        except Exception as exc:
            logger.error("Failed to dispatch document processing for %s: %s", doc_id, exc, exc_info=True)
            doc.status = "error"
            doc.processing_stage = "failed"
            doc.processing_progress = 100
            doc.error_message = str(exc)
            doc.metadata_ = record_pipeline_stage(
                doc.metadata_,
                "failed",
                state="failed",
                details={"failed_stage": "uploaded"},
                error=str(exc),
            )
            if latest_doc and latest_doc.content_hash != content_hash:
                latest_doc.is_latest_version = True
            await job_state_service.update_job(
                db,
                job.id,
                status="failed",
                progress=100,
                error_message=str(exc),
                metadata={"current_stage": "failed", "pipeline_trace": pipeline_trace(doc.metadata_)},
                completed=True,
            )
            await db.merge(doc)
            await db.commit()
            raise HTTPException(status_code=500, detail="Failed to queue document processing") from exc

        await db.refresh(doc)
        logger.info("Uploaded '%s' and queued background processing", file.filename)
        mark_document_upload()

        if doc.status == "ready":
            message = (
                "Document uploaded and processed successfully."
                if version_number == 1
                else f"Document uploaded as version {version_number} and processed successfully."
            )
        elif doc.status == "error":
            message = doc.error_message or "Document upload completed but processing failed."
        else:
            message = (
                "Document uploaded successfully and queued for processing."
                if version_number == 1
                else f"Document uploaded as version {version_number} and queued for processing."
            )

        return DocumentUploadResponse(
            id=doc_id,
            filename=normalized_filename,
            status=doc.status,
            stage=doc.processing_stage,
            processing_progress=doc.processing_progress,
            chunk_count=doc.chunk_count,
            version_number=version_number,
            message=message,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Document upload failed for %s", file.filename or "unknown")
        raise HTTPException(status_code=500, detail=f"Document upload failed: {e}")


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    include_versions: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """List all uploaded documents from PostgreSQL."""
    query = select(Document).order_by(Document.uploaded_at.desc())
    if user.role != "admin":
        query = query.where(Document.user_id == user.id)
    if not include_versions:
        query = query.where(Document.is_latest_version.is_(True))
    result = await db.execute(query)
    documents = result.scalars().all()

    return DocumentListResponse(
        documents=[_document_to_response(d) for d in documents],
        total=len(documents),
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Return processing status and progress for a document."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if user.role != "admin" and doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return DocumentStatusResponse(
        id=doc.id,
        status=doc.status,
        stage=doc.processing_stage,
        progress=doc.processing_progress,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        version_number=doc.version_number,
        is_latest_version=doc.is_latest_version,
        pipeline_trace=pipeline_trace(doc.metadata_),
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Get a single document's metadata."""
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.storage_asset))
        .where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if user.role != "admin" and doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return _document_to_response(doc)


@router.post("/{document_id}/retry", response_model=DocumentStatusResponse)
async def retry_document_processing(
    document_id: UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if user.role != "admin" and doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not doc.is_latest_version:
        raise HTTPException(status_code=409, detail="Only the latest version can be retried.")

    previous_stage = current_stage(doc.metadata_)
    doc.status = "queued"
    doc.processing_stage = "uploaded"
    doc.processing_progress = progress_for_stage(doc.processing_stage, "completed")
    doc.error_message = None
    doc.processed_at = None
    doc.metadata_ = record_pipeline_stage(
        doc.metadata_,
        "uploaded",
        state="retry_requested",
        details={
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "previous_stage": previous_stage,
        },
    )
    if doc.processing_job_id:
        await job_state_service.update_job(
            db,
            doc.processing_job_id,
            status="queued",
            progress=doc.processing_progress,
            error_message=None,
            metadata={
                "current_stage": doc.processing_stage,
                "pipeline_trace": pipeline_trace(doc.metadata_),
            },
        )
    await write_audit_log(
        db,
        user_id=user.id,
        action="DOCUMENT_RETRY",
        resource_type="document",
        resource_id=str(doc.id),
        request_ip=http_request.client.host if http_request.client else None,
        session_id=user.session_id,
        details={"version_number": doc.version_number},
    )
    await db.commit()

    try:
        job_id = await _ensure_processing_job(db, doc)
        http_request.state.document_id = str(document_id)
        http_request.state.job_id = job_id
        http_request.state.task_type = "document_processing"
        await db.commit()
        await dispatch_document_processing(str(document_id), job_id=job_id)
    except Exception as exc:
        logger.error("Failed to dispatch retried document processing for %s: %s", document_id, exc, exc_info=True)
        doc.status = "error"
        doc.processing_stage = "failed"
        doc.processing_progress = 100
        doc.error_message = str(exc)
        doc.metadata_ = record_pipeline_stage(
            doc.metadata_,
            "failed",
            state="failed",
            details={"failed_stage": "uploaded"},
            error=str(exc),
        )
        if doc.processing_job_id:
            await job_state_service.update_job(
                db,
                doc.processing_job_id,
                status="failed",
                progress=100,
                error_message=str(exc),
                metadata={
                    "current_stage": "failed",
                    "pipeline_trace": pipeline_trace(doc.metadata_),
                },
                completed=True,
            )
        await db.merge(doc)
        await db.commit()
        raise HTTPException(status_code=500, detail="Failed to queue document retry") from exc

    return DocumentStatusResponse(
        id=doc.id,
        status=doc.status,
        stage=doc.processing_stage,
        progress=doc.processing_progress,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        version_number=doc.version_number,
        is_latest_version=doc.is_latest_version,
        pipeline_trace=pipeline_trace(doc.metadata_),
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Delete a document from DB and disk."""
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.storage_asset))
        .where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if user.role != "admin" and doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found.")

    purge_result = await purge_document_artifacts(doc)
    logger.info(
        "Deleted document %s (file_removed=%s, chunks_removed=%s, bm25_removed=%s, graph_removed=%s)",
        str(document_id),
        purge_result["file_removed"],
        purge_result["chunks_removed"],
        purge_result["bm25_removed"],
        purge_result["graph_removed"],
    )

    restored_version_id = None
    promoted = None
    if doc.is_latest_version:
        promoted = await _promote_previous_version(db, doc, requeue_index=True)
        if promoted is not None:
            restored_version_id = str(promoted.id)

    await write_audit_log(
        db,
        user_id=user.id,
        action="DOCUMENT_DELETE",
        resource_type="document",
        resource_id=str(doc.id),
        request_ip=http_request.client.host if http_request.client else None,
        session_id=user.session_id,
        details={
            "file_removed": purge_result["file_removed"],
            "chunks_removed": purge_result["chunks_removed"],
            "bm25_removed": purge_result["bm25_removed"],
            "graph_removed": purge_result["graph_removed"],
            "version_number": doc.version_number,
            "restored_version_id": restored_version_id,
        },
    )
    await db.delete(doc)
    await db.commit()

    if promoted is not None:
        job_id = await _ensure_processing_job(db, promoted)
        await db.commit()
        await dispatch_document_processing(str(promoted.id), job_id=job_id)

    return {
        "message": "Document deleted and retrieval entries were invalidated.",
        "restored_version_id": restored_version_id,
    }
