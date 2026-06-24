"""
ORM models for document storage and metadata.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, String, Integer, DateTime, Text, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.persistence import DocumentChunk, DocumentContent, JobRun, StoredAsset  # noqa: F401


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    """Uploaded document metadata."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    storage_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stored_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    processing_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("job_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    version_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_latest_version: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    duplicate_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="reuse")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, default="pdf")
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    processing_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded", index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="queued"
    )  # queued | processing | ready | error
    processing_progress: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata for future phases (vision, graph, etc.)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True, default=dict
    )
    extracted_entities: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)

    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    storage_asset = relationship(StoredAsset, foreign_keys=[storage_asset_id])
    processing_job = relationship(JobRun, foreign_keys=[processing_job_id])
    content = relationship(DocumentContent, backref="document", uselist=False, cascade="all, delete-orphan")
    chunks = relationship(DocumentChunk, backref="document", cascade="all, delete-orphan")
