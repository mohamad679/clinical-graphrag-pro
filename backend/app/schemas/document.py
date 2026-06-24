"""
Pydantic schemas for document API request/response models.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class DocumentResponse(BaseModel):
    """Document metadata response."""
    id: UUID
    filename: str
    file_size: int
    chunk_count: int
    status: str
    stage: str | None = None
    processing_progress: int = 0
    uploaded_at: datetime
    processed_at: datetime | None = None
    error_message: str | None = None
    extracted_entities: list[dict] | None = None
    version_number: int = 1
    is_latest_version: bool = True
    duplicate_policy: str | None = None
    pipeline_trace: list[dict] | None = None

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    """Response returned after uploading a document."""
    id: UUID
    filename: str
    status: str
    stage: str | None = None
    processing_progress: int = 0
    chunk_count: int = 0
    version_number: int = 1
    message: str


class DocumentStatusResponse(BaseModel):
    """Background processing status for a document."""

    id: UUID
    status: str
    stage: str | None = None
    progress: int
    chunk_count: int = 0
    error_message: str | None = None
    version_number: int = 1
    is_latest_version: bool = True
    pipeline_trace: list[dict] | None = None


class DocumentListResponse(BaseModel):
    """List of documents response."""
    documents: list[DocumentResponse]
    total: int
