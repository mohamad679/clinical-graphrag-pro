"""
GDPR export and purge helpers.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.models.medical_image import MedicalImage
from app.models.user_feedback import UserFeedback
from app.models.workflow import Workflow
from app.services.bm25_index import bm25_index
from app.services.image_processing import image_processing_service
from app.services.storage import storage_service
from app.services.vector_store import vector_store_service


def _document_file_candidates(document: Document) -> list[Path]:
    settings = get_settings()
    suffix = ((document.metadata_ or {}).get("original_suffix")) or f".{document.file_type}"
    unique_suffixes = {suffix, f".{document.file_type}"}
    return [settings.upload_dir / f"{document.id}{candidate}" for candidate in unique_suffixes]


async def export_user_data(db: AsyncSession, user_id: str) -> dict:
    """Collect user-owned records into a single JSON-safe payload."""
    sessions_result = await db.execute(select(ChatSession).where(ChatSession.user_id == user_id))
    sessions = sessions_result.scalars().all()
    session_ids = [session.id for session in sessions]

    messages = []
    if session_ids:
        messages_result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id.in_(session_ids)).order_by(ChatMessage.created_at)
        )
        messages = messages_result.scalars().all()

    documents_result = await db.execute(select(Document).where(Document.user_id == user_id))
    images_result = await db.execute(select(MedicalImage).where(MedicalImage.user_id == user_id))
    workflows_result = await db.execute(select(Workflow).where(Workflow.user_id == user_id))
    feedback_result = await db.execute(select(UserFeedback).where(UserFeedback.user_id == user_id))
    audit_result = await db.execute(select(AuditLog).where(AuditLog.user_id == user_id).order_by(AuditLog.timestamp))

    return {
        "user_id": user_id,
        "sessions": jsonable_encoder(sessions),
        "messages": jsonable_encoder(messages),
        "documents": jsonable_encoder(documents_result.scalars().all()),
        "images": jsonable_encoder(images_result.scalars().all()),
        "workflows": jsonable_encoder(workflows_result.scalars().all()),
        "feedback": jsonable_encoder(feedback_result.scalars().all()),
        "audit_logs": jsonable_encoder(audit_result.scalars().all()),
    }


async def purge_user_data(db: AsyncSession, user_id: str) -> dict:
    """Hard-delete user-owned records and tombstone retrieval artifacts."""
    deleted_counts = {
        "sessions": 0,
        "messages": 0,
        "documents": 0,
        "images": 0,
        "workflows": 0,
        "feedback": 0,
        "audit_logs": 0,
        "vector_tombstones": 0,
        "bm25_tombstones": 0,
    }

    sessions_result = await db.execute(select(ChatSession).where(ChatSession.user_id == user_id))
    sessions = sessions_result.scalars().all()
    session_ids = [session.id for session in sessions]

    if session_ids:
        message_result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id.in_(session_ids))
        )
        deleted_counts["messages"] = len(message_result.scalars().all())

        feedback_rows = await db.execute(
            select(UserFeedback.id)
            .where(UserFeedback.session_id.in_([str(session_id) for session_id in session_ids]))
        )
        deleted_counts["feedback"] += len(feedback_rows.fetchall())
        await db.execute(
            delete(UserFeedback)
            .where(UserFeedback.session_id.in_([str(session_id) for session_id in session_ids]))
        )

        workflow_rows = await db.execute(
            select(Workflow.id).where(Workflow.session_id.in_(session_ids))
        )
        deleted_counts["workflows"] += len(workflow_rows.fetchall())
        await db.execute(delete(Workflow).where(Workflow.session_id.in_(session_ids)))

    documents_result = await db.execute(
        select(Document)
        .options(selectinload(Document.storage_asset))
        .where(Document.user_id == user_id)
    )
    documents = documents_result.scalars().all()
    for document in documents:
        deleted_counts["vector_tombstones"] += vector_store_service.mark_document_deleted(str(document.id))
        bm25_removed = bm25_index.mark_document_deleted(str(document.id))
        if inspect.isawaitable(bm25_removed):
            bm25_removed = await bm25_removed
        deleted_counts["bm25_tombstones"] += bm25_removed
        if document.storage_asset is not None:
            await storage_service.delete(
                bucket=document.storage_asset.bucket,
                object_key=document.storage_asset.object_key,
                storage_metadata=document.storage_asset.storage_metadata,
            )
        else:
            for candidate in _document_file_candidates(document):
                if candidate.exists():
                    candidate.unlink()
        await db.delete(document)
    deleted_counts["documents"] = len(documents)

    images_result = await db.execute(
        select(MedicalImage)
        .options(
            selectinload(MedicalImage.storage_asset),
            selectinload(MedicalImage.thumbnail_asset),
        )
        .where(MedicalImage.user_id == user_id)
    )
    images = images_result.scalars().all()
    for image in images:
        if image.storage_asset is not None:
            await storage_service.delete(
                bucket=image.storage_asset.bucket,
                object_key=image.storage_asset.object_key,
                storage_metadata=image.storage_asset.storage_metadata,
            )
        if image.thumbnail_asset is not None:
            await storage_service.delete(
                bucket=image.thumbnail_asset.bucket,
                object_key=image.thumbnail_asset.object_key,
                storage_metadata=image.thumbnail_asset.storage_metadata,
            )
        if image.storage_asset is None and image.thumbnail_asset is None:
            image_processing_service.delete_image(image.file_path, image.thumbnail_path)
        await db.delete(image)
    deleted_counts["images"] = len(images)

    feedback_rows = await db.execute(
        select(UserFeedback.id).where(UserFeedback.user_id == user_id)
    )
    deleted_counts["feedback"] += len(feedback_rows.fetchall())
    await db.execute(delete(UserFeedback).where(UserFeedback.user_id == user_id))

    audit_rows = await db.execute(
        select(AuditLog.id).where(AuditLog.user_id == user_id)
    )
    deleted_counts["audit_logs"] = len(audit_rows.fetchall())
    await db.execute(delete(AuditLog).where(AuditLog.user_id == user_id))

    workflow_rows = await db.execute(
        select(Workflow.id).where(Workflow.user_id == user_id)
    )
    deleted_counts["workflows"] += len(workflow_rows.fetchall())
    await db.execute(delete(Workflow).where(Workflow.user_id == user_id))

    for session in sessions:
        await db.delete(session)
    deleted_counts["sessions"] = len(sessions)

    await db.commit()
    return deleted_counts
