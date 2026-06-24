"""
Pydantic schemas for asynchronous audio transcription.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AudioTranscriptionResponse(BaseModel):
    id: UUID
    job_id: UUID | None = None
    status: str
    message: str
    text: str = ""


class AudioTranscriptionStatusResponse(BaseModel):
    id: UUID
    job_id: UUID | None = None
    status: str
    text: str = ""
    language: str | None = None
    error_message: str | None = None
    duration_seconds: float | None = None
    created_at: datetime
    completed_at: datetime | None = None
