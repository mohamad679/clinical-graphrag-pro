"""
Images / Vision API endpoints.
Upload, analyze, annotate, and serve medical images.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.medical_image import MedicalImage, ImageAnnotation
from app.schemas.image import (
    ImageUploadResponse,
    ImageResponse,
    ImageListResponse,
    ImageAnalyzeRequest,
    ImageAnalysisResult,
    AnnotationCreate,
    AnnotationResponse,
)
from app.services.image_processing import image_processing_service
from app.services.vision import vision_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["Medical Images"])


# ── Upload ───────────────────────────────────────────────


@router.post("/upload", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a medical image (PNG, JPEG, TIFF, DICOM)."""
    content = await file.read()

    # Validate
    error = image_processing_service.validate_image(
        file.filename or "unknown",
        file.content_type or "application/octet-stream",
        len(content),
    )
    if error:
        raise HTTPException(status_code=400, detail=error)

    # Save to disk
    saved = await image_processing_service.save_image(content, file.filename or "image.png")

    # Create DB record
    image = MedicalImage(
        filename=saved["filename"],
        original_filename=file.filename or "image.png",
        file_path=saved["file_path"],
        thumbnail_path=saved["thumbnail_path"],
        file_size=saved["file_size"],
        mime_type=file.content_type or "image/png",
        width=saved["width"],
        height=saved["height"],
        analysis_status="pending",
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)

    return ImageUploadResponse(
        id=image.id,
        filename=image.original_filename,
        file_size=image.file_size,
        width=image.width,
        height=image.height,
        analysis_status=image.analysis_status,
        thumbnail_url=image_processing_service.get_thumbnail_url(image.filename),
        message="Image uploaded successfully. Call POST /api/images/{id}/analyze to analyze.",
    )


# ── Analyze ──────────────────────────────────────────────


@router.post("/{image_id}/analyze", response_model=ImageAnalysisResult)
async def analyze_image(
    image_id: UUID,
    body: ImageAnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Run VLM analysis on an uploaded image."""
    result = await db.execute(select(MedicalImage).where(MedicalImage.id == image_id))
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Read image data
    image_path = Path(image.file_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on disk")

    image_data = image_path.read_bytes()

    # Update status
    image.analysis_status = "analyzing"
    await db.commit()

    # Run analysis
    additional_context = body.additional_context if body else ""
    analysis = await vision_service.analyze_image(
        image_data, image.mime_type, additional_context
    )

    # Save analysis result
    image.analysis_result = analysis
    image.analysis_status = "completed" if "error" not in analysis else "failed"
    image.analyzed_at = datetime.now(timezone.utc)

    # Extract detected metadata
    image.modality = analysis.get("modality_detected")
    image.body_part = analysis.get("body_part_detected")

    # Auto-create annotations from findings
    auto_annotations = vision_service.extract_annotations_from_analysis(analysis)
    for ann_data in auto_annotations:
        annotation = ImageAnnotation(image_id=image.id, **ann_data)
        db.add(annotation)

    await db.commit()
    await db.refresh(image)

    return ImageAnalysisResult(**analysis)


# ── List & Get ───────────────────────────────────────────


@router.get("", response_model=ImageListResponse)
async def list_images(db: AsyncSession = Depends(get_db)):
    """List all uploaded medical images."""
    result = await db.execute(
        select(MedicalImage)
        .options(selectinload(MedicalImage.annotations))
        .order_by(MedicalImage.uploaded_at.desc())
    )
    images = result.scalars().all()

    responses = []
    for img in images:
        resp = _image_to_response(img)
        responses.append(resp)

    return ImageListResponse(images=responses, total=len(responses))


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(image_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a single image with its annotations."""
    result = await db.execute(
        select(MedicalImage)
        .options(selectinload(MedicalImage.annotations))
        .where(MedicalImage.id == image_id)
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    return _image_to_response(image)


@router.delete("/{image_id}")
async def delete_image(image_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete an image and its annotations."""
    result = await db.execute(select(MedicalImage).where(MedicalImage.id == image_id))
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Delete files from disk
    image_processing_service.delete_image(image.file_path, image.thumbnail_path)

    await db.delete(image)
    await db.commit()
    return {"message": "Image deleted"}


# ── Annotations CRUD ─────────────────────────────────────


@router.post("/{image_id}/annotations", response_model=AnnotationResponse)
async def create_annotation(
    image_id: UUID,
    body: AnnotationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a manual annotation to an image."""
    # Verify image exists
    result = await db.execute(select(MedicalImage).where(MedicalImage.id == image_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Image not found")

    annotation = ImageAnnotation(image_id=image_id, **body.model_dump())
    db.add(annotation)
    await db.commit()
    await db.refresh(annotation)
    return annotation


@router.get("/{image_id}/annotations", response_model=list[AnnotationResponse])
async def list_annotations(
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all annotations for an image."""
    result = await db.execute(
        select(ImageAnnotation)
        .where(ImageAnnotation.image_id == image_id)
        .order_by(ImageAnnotation.created_at)
    )
    return result.scalars().all()


@router.delete("/{image_id}/annotations/{annotation_id}")
async def delete_annotation(
    image_id: UUID,
    annotation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single annotation."""
    result = await db.execute(
        select(ImageAnnotation).where(
            ImageAnnotation.id == annotation_id,
            ImageAnnotation.image_id == image_id,
        )
    )
    annotation = result.scalar_one_or_none()
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    await db.delete(annotation)
    await db.commit()
    return {"message": "Annotation deleted"}


# ── Serve Files ──────────────────────────────────────────


@router.get("/files/{filename}")
async def serve_image_file(filename: str):
    """Serve an uploaded image file."""
    path = image_processing_service.image_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@router.get("/thumbnails/{filename}")
async def serve_thumbnail(filename: str):
    """Serve a thumbnail image."""
    path = image_processing_service.thumbnail_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path)


# ── Helpers ──────────────────────────────────────────────


def _image_to_response(img: MedicalImage) -> ImageResponse:
    """Convert ORM model to response with computed URLs."""
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
        analysis_status=img.analysis_status,
        analysis_result=img.analysis_result,
        annotations=[AnnotationResponse.model_validate(a) for a in img.annotations],
        uploaded_at=img.uploaded_at,
        analyzed_at=img.analyzed_at,
        image_url=image_processing_service.get_image_url(img.filename),
        thumbnail_url=image_processing_service.get_thumbnail_url(img.filename),
    )
