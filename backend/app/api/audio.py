"""
Audio processing API endpoints.
Asynchronous upload and transcription with durable job state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import User, require_role
from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.core.database import get_db
from app.models.persistence import AudioTranscript, StoredAsset
from app.schemas.audio import AudioTranscriptionResponse, AudioTranscriptionStatusResponse
from app.services.audio_processing import audio_processing_service
from app.services.job_state import job_state_service
from app.worker import dispatch_audio_transcription

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/audio",
    tags=["Audio"],
    dependencies=[Depends(require_role("physician"))],
)
settings = get_settings()


@router.post("/transcribe", response_model=AudioTranscriptionResponse)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Upload audio and queue asynchronous transcription."""
    try:
        content = await file.read()
        validated = audio_processing_service.validate_audio_upload(
            file.filename or "recording.webm",
            file.content_type or "application/octet-stream",
            content,
        )
        stored = await audio_processing_service.store_audio_upload(
            content=content,
            validated=validated,
        )

        asset = StoredAsset(
            owner_user_id=user.id,
            category="audio",
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

        retention_expires_at = datetime.now(timezone.utc) + timedelta(days=settings.audio_raw_retention_days)
        transcript = AudioTranscript(
            user_id=user.id,
            storage_asset_id=asset.id,
            filename=stored.original_filename,
            original_filename=validated.normalized_filename,
            mime_type=validated.mime_type,
            file_size=len(content),
            duration_seconds=validated.duration_seconds,
            language=settings.audio_default_language if not settings.audio_allow_auto_language_detection else None,
            status="queued",
            retention_expires_at=retention_expires_at,
            metadata_=validated.validation_metadata,
        )
        db.add(transcript)
        await db.flush()

        job = await job_state_service.create_job(
            db,
            job_type="audio_transcription",
            entity_type="audio_transcript",
            entity_id=str(transcript.id),
            created_by_user_id=user.id,
            payload={
                "filename": validated.normalized_filename,
                "detected_kind": validated.detected_kind,
                "duration_seconds": validated.duration_seconds,
            },
            metadata={"transcript_status": "queued"},
            dedupe_active=False,
            max_retries=settings.audio_provider_max_retries,
            retry_backoff_seconds=settings.audio_provider_retry_backoff_seconds,
            timeout_seconds=settings.audio_transcription_timeout_seconds,
        )
        transcript.transcription_job_id = job.id
        await write_audit_log(
            db,
            user_id=user.id,
            action="AUDIO_UPLOAD",
            resource_type="audio_transcript",
            resource_id=str(transcript.id),
            request_ip=request.client.host if request and request.client else None,
            session_id=user.session_id,
            details={
                "filename": transcript.original_filename,
                "duration_seconds": transcript.duration_seconds,
            },
        )
        await db.commit()
        await db.refresh(transcript)

        dispatch_result = await dispatch_audio_transcription(str(transcript.id), job_id=str(job.id))
        if dispatch_result.get("transport") == "local-eager":
            await db.refresh(transcript)
            return AudioTranscriptionResponse(
                id=transcript.id,
                job_id=transcript.transcription_job_id,
                status=transcript.status,
                message="Audio transcribed successfully.",
                text=transcript.transcript_text or "",
            )

        return AudioTranscriptionResponse(
            id=transcript.id,
            job_id=transcript.transcription_job_id,
            status=transcript.status,
            message="Audio uploaded and queued for transcription.",
            text="",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to queue audio transcription for %s", file.filename or "audio")
        raise HTTPException(status_code=500, detail=f"Failed to queue audio transcription: {exc}") from exc


@router.get("/transcripts/{transcript_id}", response_model=AudioTranscriptionStatusResponse)
async def get_transcription_status(
    transcript_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Return transcription status and the completed transcript text when available."""
    result = await db.execute(
        select(AudioTranscript)
        .options(selectinload(AudioTranscript.transcription_job))
        .where(AudioTranscript.id == transcript_id)
    )
    transcript = result.scalar_one_or_none()
    if transcript is None:
        raise HTTPException(status_code=404, detail="Audio transcript not found")
    if user.role != "admin" and transcript.user_id != user.id:
        raise HTTPException(status_code=404, detail="Audio transcript not found")

    return AudioTranscriptionStatusResponse(
        id=transcript.id,
        job_id=transcript.transcription_job_id,
        status=transcript.status,
        text=transcript.transcript_text or "",
        language=transcript.language,
        error_message=transcript.error_message,
        duration_seconds=transcript.duration_seconds,
        created_at=transcript.created_at,
        completed_at=transcript.completed_at,
    )
