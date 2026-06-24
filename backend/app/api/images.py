"""
Images / Vision API endpoints.
Upload, analyze, annotate, and serve medical images.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import User, require_role
from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.core.database import get_db
from app.core.retrieval_scope import retrieval_scope_for_user
from app.models.medical_image import MedicalImage, ImageAnnotation
from app.models.persistence import StoredAsset
from app.schemas.image import (
    ImageUploadResponse,
    ImageResponse,
    ImageListResponse,
    ImageAnalyzeRequest,
    ImageAnalysisDispatchResponse,
    AnnotationCreate,
    AnnotationResponse,
)
from app.services.entity_normalization import entity_normalization_service
from app.services.graph import temporal_graph_service
from app.services.image_processing import image_processing_service
from app.services.job_state import job_state_service
from app.services.vision import vision_service
from app.worker import dispatch_image_analysis

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/images",
    tags=["Medical Images"],
    dependencies=[Depends(require_role("physician"))],
)
settings = get_settings()


# ── Upload ───────────────────────────────────────────────


@router.post("/upload", response_model=ImageUploadResponse)
async def upload_image(
    http_request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Upload a medical image (PNG, JPEG, TIFF, DICOM)."""
    try:
        capability = vision_service.get_analysis_capability()
        content = await file.read()
        validated = await image_processing_service.validate_image_upload(
            file.filename or "unknown",
            file.content_type or "application/octet-stream",
            content,
        )

        saved = await image_processing_service.save_image(
            validated.sanitized_content,
            validated.normalized_filename,
            content_type=validated.mime_type,
        )

        # Create DB record
        file_asset = StoredAsset(
            owner_user_id=user.id,
            category="image",
            provider=saved["file_asset"].provider,
            bucket=saved["file_asset"].bucket,
            object_key=saved["file_asset"].object_key,
            original_filename=saved["file_asset"].original_filename,
            content_type=saved["file_asset"].content_type,
            size_bytes=saved["file_asset"].size_bytes,
            checksum=saved["file_asset"].checksum,
            encryption_status=saved["file_asset"].encryption_status,
            storage_metadata=saved["file_asset"].storage_metadata,
        )
        db.add(file_asset)
        await db.flush()
        thumbnail_asset_id = None
        if saved["thumbnail_asset"] is not None:
            thumbnail_asset = StoredAsset(
                owner_user_id=user.id,
                category="image_thumbnail",
                provider=saved["thumbnail_asset"].provider,
                bucket=saved["thumbnail_asset"].bucket,
                object_key=saved["thumbnail_asset"].object_key,
                original_filename=saved["thumbnail_asset"].original_filename,
                content_type=saved["thumbnail_asset"].content_type,
                size_bytes=saved["thumbnail_asset"].size_bytes,
                checksum=saved["thumbnail_asset"].checksum,
                encryption_status=saved["thumbnail_asset"].encryption_status,
                storage_metadata=saved["thumbnail_asset"].storage_metadata,
            )
            db.add(thumbnail_asset)
            await db.flush()
            thumbnail_asset_id = thumbnail_asset.id

        image = MedicalImage(
            user_id=user.id,
            tenant_id=user.tenant_id or user.id,
            storage_asset_id=file_asset.id,
            thumbnail_asset_id=thumbnail_asset_id,
            filename=saved["filename"],
            original_filename=validated.normalized_filename,
            file_path=saved["file_path"],
            thumbnail_path=saved["thumbnail_path"],
            file_size=saved["file_size"],
            mime_type=validated.mime_type,
            width=validated.width or saved["width"],
            height=validated.height or saved["height"],
            dicom_metadata=validated.dicom_metadata,
            validation_metadata=validated.validation_metadata,
            phi_scrubbed=validated.phi_scrubbed,
            manual_review_required=validated.manual_review_required,
            manual_review_status="pending_review" if validated.manual_review_required else "not_required",
            analysis_status="uploaded",
        )
        db.add(image)
        await db.commit()
        await db.refresh(image)
        if http_request is not None:
            http_request.state.image_id = str(image.id)
        upload_message = "Image uploaded successfully."
        if settings.image_auto_analyze_on_upload and capability["available"]:
            upload_message = "Image uploaded successfully. Analysis can start automatically from the UI."
        elif not capability["available"]:
            upload_message = "Image uploaded successfully. Analysis is unavailable until a vision provider is configured."

        return ImageUploadResponse(
            id=image.id,
            analysis_job_id=image.analysis_job_id,
            filename=image.original_filename,
            file_size=image.file_size,
            width=image.width,
            height=image.height,
            analysis_status=image.analysis_status,
            manual_review_required=image.manual_review_required,
            analysis_available=bool(capability["available"]),
            analysis_unavailable_reason=None if capability["available"] else str(capability["reason"]),
            auto_analysis_enabled=bool(settings.image_auto_analyze_on_upload and capability["available"]),
            thumbnail_url=f"/api/images/{image.id}/thumbnail" if image.thumbnail_asset_id else None,
            image_url=f"/api/images/{image.id}/file",
            message=upload_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Image upload failed for %s", file.filename or "unknown")
        raise HTTPException(status_code=500, detail=f"Image upload failed: {e}")


# ── Analyze ──────────────────────────────────────────────


async def _ensure_analysis_job(
    db: AsyncSession,
    image: MedicalImage,
    *,
    user_id: str | None,
    additional_context: str = "",
) -> str:
    if image.analysis_job_id is not None:
        return str(image.analysis_job_id)

    job = await job_state_service.create_job(
        db,
        job_type="image_analysis",
        entity_type="medical_image",
        entity_id=str(image.id),
        created_by_user_id=user_id,
        payload={
            "filename": image.original_filename,
            "additional_context": additional_context,
        },
        metadata={"analysis_status": "queued"},
        dedupe_active=False,
    )
    image.analysis_job_id = job.id
    await db.flush()
    return str(job.id)


async def _dispatch_image_analysis_background(
    image_id: str,
    *,
    additional_context: str = "",
    job_id: str,
) -> None:
    try:
        await dispatch_image_analysis(
            image_id,
            additional_context=additional_context,
            job_id=job_id,
        )
    except Exception:
        logger.exception("Background image analysis dispatch failed for %s", image_id)


@router.post("/{image_id}/analyze", response_model=ImageAnalysisDispatchResponse)
async def analyze_image(
    image_id: UUID,
    http_request: Request,
    background_tasks: BackgroundTasks,
    body: ImageAnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Queue asynchronous VLM analysis on an uploaded image."""
    result = await db.execute(
        select(MedicalImage)
        .options(selectinload(MedicalImage.storage_asset), selectinload(MedicalImage.thumbnail_asset))
        .where(MedicalImage.id == image_id)
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    if user.role != "admin" and image.user_id != user.id:
        raise HTTPException(status_code=404, detail="Image not found")

    additional_context = body.additional_context if body else ""
    try:
        capability = vision_service.get_analysis_capability()
        if not capability["available"]:
            image.last_error = str(capability["reason"])
            if image.analysis_result is None:
                image.analysis_status = "uploaded"
            await db.commit()
            raise HTTPException(status_code=503, detail=str(capability["reason"]))

        job_id = await _ensure_analysis_job(
            db,
            image,
            user_id=user.id,
            additional_context=additional_context,
        )
        image.analysis_status = "queued"
        image.analysis_requested_at = datetime.now(timezone.utc)
        image.last_error = None
        if http_request is not None:
            http_request.state.image_id = str(image.id)
            http_request.state.job_id = job_id
            http_request.state.task_type = "image_analysis"
        if image.analysis_job_id:
            await job_state_service.update_job(
                db,
                image.analysis_job_id,
                status="queued",
                progress=0,
                metadata={
                    "analysis_status": "queued",
                    "additional_context_present": bool(additional_context.strip()),
                },
            )
        await db.commit()
        if settings.celery_task_always_eager:
            background_tasks.add_task(
                _dispatch_image_analysis_background,
                str(image.id),
                additional_context=additional_context,
                job_id=job_id,
            )
        else:
            await dispatch_image_analysis(
                str(image.id),
                additional_context=additional_context,
                job_id=job_id,
            )
        return ImageAnalysisDispatchResponse(
            id=image.id,
            analysis_job_id=image.analysis_job_id,
            analysis_status=image.analysis_status,
            message="Image analysis queued successfully.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        await job_state_service.update_job(
            db,
            image.analysis_job_id,
            status="failed",
            progress=100,
            error_message=str(exc),
            completed=True,
        )
        raise HTTPException(status_code=404, detail="Image file not found") from exc
    except Exception as exc:
        logger.exception("Failed to dispatch image analysis for %s", image_id)
        image.analysis_status = "failed"
        image.last_error = str(exc)
        if image.analysis_job_id:
            await job_state_service.update_job(
                db,
                image.analysis_job_id,
                status="failed",
                progress=100,
                error_message=str(exc),
                metadata={"analysis_status": "failed"},
                completed=True,
            )
        await db.commit()
        raise HTTPException(status_code=500, detail="Failed to queue image analysis") from exc


# ── List & Get ───────────────────────────────────────────


@router.get("", response_model=ImageListResponse)
async def list_images(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """List all uploaded medical images."""
    query = (
        select(MedicalImage)
        .options(selectinload(MedicalImage.annotations))
        .order_by(MedicalImage.uploaded_at.desc())
    )
    if user.role != "admin":
        query = query.where(MedicalImage.user_id == user.id)
    result = await db.execute(query)
    images = result.scalars().all()

    responses = []
    for img in images:
        resp = _image_to_response(img)
        responses.append(resp)

    return ImageListResponse(images=responses, total=len(responses))


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Get a single image with its annotations."""
    result = await db.execute(
        select(MedicalImage)
        .options(selectinload(MedicalImage.annotations))
        .where(MedicalImage.id == image_id)
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    if user.role != "admin" and image.user_id != user.id:
        raise HTTPException(status_code=404, detail="Image not found")

    return _image_to_response(image)


@router.delete("/{image_id}")
async def delete_image(
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Delete an image and its annotations."""
    result = await db.execute(
        select(MedicalImage)
        .options(selectinload(MedicalImage.storage_asset), selectinload(MedicalImage.thumbnail_asset))
        .where(MedicalImage.id == image_id)
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    if user.role != "admin" and image.user_id != user.id:
        raise HTTPException(status_code=404, detail="Image not found")

    if image.storage_asset is not None:
        from app.services.storage import storage_service

        await storage_service.delete(
            bucket=image.storage_asset.bucket,
            object_key=image.storage_asset.object_key,
            storage_metadata=image.storage_asset.storage_metadata,
        )
    if image.thumbnail_asset is not None:
        from app.services.storage import storage_service

        await storage_service.delete(
            bucket=image.thumbnail_asset.bucket,
            object_key=image.thumbnail_asset.object_key,
            storage_metadata=image.thumbnail_asset.storage_metadata,
        )
    if image.storage_asset is None and image.thumbnail_asset is None:
        image_processing_service.delete_image(image.file_path, image.thumbnail_path)

    await temporal_graph_service.delete_image_artifacts(str(image.id))
    await db.delete(image)
    await db.commit()
    return {"message": "Image deleted"}


# ── Annotations CRUD ─────────────────────────────────────


@router.post("/{image_id}/annotations", response_model=AnnotationResponse)
async def create_annotation(
    image_id: UUID,
    body: AnnotationCreate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Add a manual annotation to an image."""
    # Verify image exists
    result = await db.execute(select(MedicalImage).where(MedicalImage.id == image_id))
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    if user.role != "admin" and image.user_id != user.id:
        raise HTTPException(status_code=404, detail="Image not found")

    payload = body.model_dump()
    payload["source"] = payload.get("source") or "user"
    annotation = ImageAnnotation(
        image_id=image_id,
        version_number=1,
        is_current=True,
        corrected_by=user.id,
        corrected_at=datetime.now(timezone.utc),
        review_status="clinician_reviewed",
        metadata_={"created_via": "annotation_create"},
        **payload,
    )
    db.add(annotation)
    image.analysis_status = "clinician_reviewed" if image.analysis_status != "failed" else image.analysis_status
    image.manual_review_status = "reviewed"
    image.manual_review_required = False
    await db.flush()
    await write_audit_log(
        db,
        user_id=user.id,
        action="IMAGE_ANNOTATION_CREATE",
        resource_type="image_annotation",
        resource_id=str(annotation.id),
        request_ip=http_request.client.host if http_request.client else None,
        session_id=user.session_id,
        details={"image_id": str(image_id), "source": annotation.source},
    )
    await db.commit()
    await db.refresh(annotation)
    return annotation


@router.put("/{image_id}/annotations/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(
    image_id: UUID,
    annotation_id: UUID,
    body: AnnotationCreate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Create a new annotation version rather than mutating the old one."""
    image_result = await db.execute(select(MedicalImage).where(MedicalImage.id == image_id))
    image = image_result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    if user.role != "admin" and image.user_id != user.id:
        raise HTTPException(status_code=404, detail="Image not found")

    result = await db.execute(
        select(ImageAnnotation).where(
            ImageAnnotation.id == annotation_id,
            ImageAnnotation.image_id == image_id,
            ImageAnnotation.deleted_at.is_(None),
        )
    )
    annotation = result.scalar_one_or_none()
    if annotation is None:
        raise HTTPException(status_code=404, detail="Annotation not found")

    now = datetime.now(timezone.utc)
    annotation.is_current = False
    annotation.corrected_at = now

    replacement = ImageAnnotation(
        image_id=image_id,
        previous_annotation_id=annotation.id,
        version_number=(annotation.version_number or 1) + 1,
        is_current=True,
        corrected_by=user.id,
        corrected_at=now,
        review_status="corrected",
        metadata_={"created_via": "annotation_update"},
        **body.model_dump(),
    )
    db.add(replacement)
    image.analysis_status = "corrected" if image.analysis_status != "failed" else image.analysis_status
    image.manual_review_status = "corrected"
    image.manual_review_required = False
    await db.flush()
    await write_audit_log(
        db,
        user_id=user.id,
        action="IMAGE_ANNOTATION_UPDATE",
        resource_type="image_annotation",
        resource_id=str(annotation.id),
        request_ip=http_request.client.host if http_request.client else None,
        session_id=user.session_id,
        details={"image_id": str(image_id), "replacement_annotation_id": str(replacement.id)},
    )
    await db.commit()
    await db.refresh(replacement)
    return replacement


@router.get("/{image_id}/annotations", response_model=list[AnnotationResponse])
async def list_annotations(
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """List all annotations for an image."""
    image_result = await db.execute(select(MedicalImage).where(MedicalImage.id == image_id))
    image = image_result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    if user.role != "admin" and image.user_id != user.id:
        raise HTTPException(status_code=404, detail="Image not found")

    result = await db.execute(
        select(ImageAnnotation)
        .where(ImageAnnotation.image_id == image_id)
        .order_by(ImageAnnotation.created_at)
    )
    return [
        annotation
        for annotation in result.scalars().all()
        if annotation.deleted_at is None and annotation.is_current
    ]


@router.delete("/{image_id}/annotations/{annotation_id}")
async def delete_annotation(
    image_id: UUID,
    annotation_id: UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Delete a single annotation."""
    image_result = await db.execute(select(MedicalImage).where(MedicalImage.id == image_id))
    image = image_result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    if user.role != "admin" and image.user_id != user.id:
        raise HTTPException(status_code=404, detail="Image not found")

    result = await db.execute(
        select(ImageAnnotation).where(
            ImageAnnotation.id == annotation_id,
            ImageAnnotation.image_id == image_id,
            ImageAnnotation.deleted_at.is_(None),
        )
    )
    annotation = result.scalar_one_or_none()
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    annotation.is_current = False
    annotation.deleted_at = datetime.now(timezone.utc)
    annotation.corrected_by = user.id
    image.analysis_status = "corrected" if image.analysis_status != "failed" else image.analysis_status
    image.manual_review_status = "corrected"
    await write_audit_log(
        db,
        user_id=user.id,
        action="IMAGE_ANNOTATION_DELETE",
        resource_type="image_annotation",
        resource_id=str(annotation.id),
        request_ip=http_request.client.host if http_request.client else None,
        session_id=user.session_id,
        details={"image_id": str(image_id)},
    )
    await db.commit()
    return {"message": "Annotation deleted"}


# ── Serve Files ──────────────────────────────────────────


async def _get_authorized_image(
    db: AsyncSession,
    image_id: UUID,
    user: User,
) -> MedicalImage:
    result = await db.execute(
        select(MedicalImage)
        .options(selectinload(MedicalImage.storage_asset), selectinload(MedicalImage.thumbnail_asset))
        .where(MedicalImage.id == image_id)
    )
    image = result.scalar_one_or_none()
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    if user.role != "admin":
        scope = retrieval_scope_for_user(user)
        if image.tenant_id != scope.tenant_id or image.user_id != scope.principal_user_id:
            raise HTTPException(status_code=404, detail="Image not found")
    return image


@router.get("/{image_id}/file")
async def serve_image_by_id(
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Serve an uploaded image after DB-backed authorization."""
    image = await _get_authorized_image(db, image_id, user)
    try:
        content = await image_processing_service.read_image_bytes(image)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    return Response(content=content, media_type=image.mime_type)


@router.get("/{image_id}/thumbnail")
async def serve_thumbnail_by_id(
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("physician")),
):
    """Serve an image thumbnail after DB-backed authorization."""
    image = await _get_authorized_image(db, image_id, user)
    content = await image_processing_service.read_thumbnail_bytes(image)
    if content is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=content, media_type="image/webp")


@router.get("/files/{filename}")
async def serve_image_file(filename: str, _user: User = Depends(require_role("physician"))):
    """Legacy filename route intentionally does not serve protected resources."""
    _resolve_safe_upload_file(image_processing_service.image_dir, filename)
    raise HTTPException(status_code=404, detail="File not found")


@router.get("/thumbnails/{filename}")
async def serve_thumbnail(filename: str, _user: User = Depends(require_role("physician"))):
    """Legacy filename thumbnail route intentionally does not serve protected resources."""
    _resolve_safe_upload_file(image_processing_service.thumbnail_dir, filename)
    raise HTTPException(status_code=404, detail="Thumbnail not found")


# ── Helpers ──────────────────────────────────────────────


def _resolve_safe_upload_file(base_dir: Path, filename: str) -> Path:
    """Resolve a filename inside a base upload directory, blocking traversal."""
    candidate_name = Path(filename).name
    if not candidate_name or candidate_name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    resolved_base = base_dir.resolve()
    resolved_file = (base_dir / candidate_name).resolve()
    try:
        resolved_file.relative_to(resolved_base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")

    return resolved_file


def _extract_normalized_entities(analysis: dict) -> list[dict]:
    """Normalize clinically relevant entities from an image analysis payload."""
    text_fragments: list[str] = []

    summary = analysis.get("summary")
    if isinstance(summary, str) and summary.strip():
        text_fragments.append(summary.strip())

    for finding in analysis.get("findings", []):
        if not isinstance(finding, dict):
            continue
        for key in ("description", "location"):
            value = finding.get(key)
            if isinstance(value, str) and value.strip():
                text_fragments.append(value.strip())

    for item in analysis.get("differential_diagnosis", []):
        if not isinstance(item, dict):
            continue
        condition = item.get("condition")
        if isinstance(condition, str) and condition.strip():
            text_fragments.append(condition.strip())

    if not text_fragments:
        return []

    normalized = entity_normalization_service.normalize_with_fallback(". ".join(text_fragments))
    return [entity.model_dump() for entity in normalized if not entity.is_ungrounded]


def _image_to_response(img: MedicalImage) -> ImageResponse:
    """Convert ORM model to response with computed URLs."""
    capability = vision_service.get_analysis_capability()
    analysis_available = bool(capability["available"])
    analysis_status = img.analysis_status
    last_error = img.last_error
    analysis_result = img.analysis_result
    if not analysis_available and analysis_status == "failed":
        analysis_status = "uploaded"
        last_error = None
        analysis_result = None
    return ImageResponse(
        id=img.id,
        filename=img.filename,
        original_filename=img.original_filename,
        file_size=img.file_size,
        width=img.width,
        height=img.height,
        mime_type=img.mime_type,
        modality=img.modality,
        body_part=img.body_part,
        analysis_status=analysis_status,
        manual_review_required=bool(img.manual_review_required),
        manual_review_status=img.manual_review_status or "pending",
        phi_scrubbed=bool(img.phi_scrubbed),
        last_error=last_error,
        analysis_available=analysis_available,
        analysis_unavailable_reason=None if analysis_available else str(capability["reason"]),
        auto_analysis_enabled=bool(settings.image_auto_analyze_on_upload and analysis_available),
        validation_metadata=img.validation_metadata,
        analysis_result=analysis_result,
        annotations=[
            AnnotationResponse.model_validate(a)
            for a in img.annotations
            if a.deleted_at is None and a.is_current
        ],
        uploaded_at=img.uploaded_at,
        analyzed_at=img.analyzed_at,
        image_url=f"/api/images/{img.id}/file",
        thumbnail_url=f"/api/images/{img.id}/thumbnail" if img.thumbnail_asset_id or img.thumbnail_path else None,
    )
