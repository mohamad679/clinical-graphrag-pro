"""
Pydantic schemas for the images/vision API.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


# ── Analysis Results ─────────────────────────────────────


class Finding(BaseModel):
    description: str
    location: str = ""
    severity: str = "normal"
    confidence: float = 0.0
    bbox: dict | None = None


class DifferentialDiagnosis(BaseModel):
    condition: str
    probability: float


class ImageAnalysisResult(BaseModel):
    summary: str = ""
    modality_detected: str = ""
    body_part_detected: str = ""
    findings: list[Finding] = []
    recommendations: list[str] = []
    differential_diagnosis: list[DifferentialDiagnosis] = []
    model_used: str = ""
    error: str | None = None


# ── Annotations ──────────────────────────────────────────


class AnnotationBase(BaseModel):
    annotation_type: str  # bbox | polygon | point | freeform | text
    label: str
    description: str | None = None
    color: str = "#ef4444"
    confidence: float | None = None
    geometry: dict
    source: str = "user"  # ai | user


class AnnotationCreate(AnnotationBase):
    pass


class AnnotationResponse(AnnotationBase):
    id: UUID
    image_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Image ────────────────────────────────────────────────


class ImageUploadResponse(BaseModel):
    id: UUID
    filename: str
    file_size: int
    width: int | None = None
    height: int | None = None
    modality: str | None = None
    analysis_status: str
    thumbnail_url: str | None = None
    message: str


class ImageResponse(BaseModel):
    id: UUID
    filename: str
    original_filename: str
    file_size: int
    width: int | None = None
    height: int | None = None
    mime_type: str
    modality: str | None = None
    body_part: str | None = None
    analysis_status: str
    analysis_result: dict | None = None
    annotations: list[AnnotationResponse] = []
    uploaded_at: datetime
    analyzed_at: datetime | None = None
    image_url: str = ""
    thumbnail_url: str | None = None

    model_config = {"from_attributes": True}


class ImageListResponse(BaseModel):
    images: list[ImageResponse]
    total: int


class ImageAnalyzeRequest(BaseModel):
    """Optional body for triggering re-analysis with extra context."""
    additional_context: str = ""
