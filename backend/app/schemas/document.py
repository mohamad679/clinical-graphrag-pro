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
    uploaded_at: datetime
    processed_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    """Response returned after uploading a document."""
    id: UUID
    filename: str
    status: str
    chunk_count: int = 0
    message: str


class DocumentListResponse(BaseModel):
    """List of documents response."""
    documents: list[DocumentResponse]
    total: int
