"""
Pydantic schemas for the images/vision API.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel

from app.schemas.entity_normalization import NormalizedEntity


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
    normalized_entities: list[NormalizedEntity] = []
    model_used: str = ""
    error: str | None = None


class ImageAnalysisDispatchResponse(BaseModel):
    id: UUID
    analysis_job_id: UUID | None = None
    analysis_status: str
    message: str


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
    version_number: int = 1
    is_current: bool = True
    corrected_by: str | None = None
    corrected_at: datetime | None = None
    review_status: str = "ai_generated"
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Image ────────────────────────────────────────────────


class ImageUploadResponse(BaseModel):
    id: UUID
    analysis_job_id: UUID | None = None
    filename: str
    file_size: int
    width: int | None = None
    height: int | None = None
    modality: str | None = None
    analysis_status: str
    manual_review_required: bool = False
    analysis_available: bool = True
    analysis_unavailable_reason: str | None = None
    auto_analysis_enabled: bool = False
    thumbnail_url: str | None = None
    image_url: str | None = None
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
    manual_review_required: bool = False
    manual_review_status: str = "pending"
    phi_scrubbed: bool = False
    last_error: str | None = None
    analysis_available: bool = True
    analysis_unavailable_reason: str | None = None
    auto_analysis_enabled: bool = False
    validation_metadata: dict | None = None
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
