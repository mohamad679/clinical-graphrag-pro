"""
MedicalImage and ImageAnnotation ORM models.
Stores image metadata, analysis results, and user-drawn annotations.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, Float,
    ForeignKey, JSON,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class MedicalImage(Base):
    """Uploaded medical image with analysis metadata."""

    __tablename__ = "medical_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(500), nullable=False)
    original_filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    thumbnail_path = Column(String(1000), nullable=True)

    # File metadata
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    # Medical metadata
    modality = Column(String(50), nullable=True)  # X-ray, CT, MRI, Ultrasound, etc.
    body_part = Column(String(100), nullable=True)
    patient_id = Column(String(100), nullable=True)  # anonymized
    study_date = Column(DateTime(timezone=True), nullable=True)
    dicom_metadata = Column(JSONB, nullable=True)

    # Analysis
    analysis_status = Column(
        String(20), default="pending"
    )  # pending | analyzing | completed | failed
    analysis_result = Column(JSONB, nullable=True)
    # Expected structure:
    # {
    #   "findings": [{"description": "...", "confidence": 0.85, "severity": "moderate"}],
    #   "recommendations": ["..."],
    #   "summary": "...",
    #   "model_used": "gemini-2.0-flash"
    # }

    # Optional link to a chat message that triggered analysis
    chat_message_id = Column(UUID(as_uuid=True), nullable=True)

    # Timestamps
    uploaded_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    analyzed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    annotations = relationship(
        "ImageAnnotation", back_populates="image", cascade="all, delete-orphan"
    )


class ImageAnnotation(Base):
    """A single annotation on a medical image (bounding box, mask, etc.)."""

    __tablename__ = "image_annotations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True),
        ForeignKey("medical_images.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Annotation content
    annotation_type = Column(
        String(30), nullable=False
    )  # bbox | polygon | point | freeform | text
    label = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(20), default="#ef4444")
    confidence = Column(Float, nullable=True)

    # Geometry — normalized coordinates (0.0 - 1.0)
    geometry = Column(JSONB, nullable=False)
    # bbox:    {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
    # polygon: {"points": [[0.1, 0.2], [0.3, 0.4], ...]}
    # point:   {"x": 0.5, "y": 0.5}

    # Source
    source = Column(String(20), default="ai")  # ai | user

    # Timestamps
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    image = relationship("MedicalImage", back_populates="annotations")
