"""
Pydantic schemas for chat API request/response models.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


# ── Requests ─────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Incoming chat message from the user."""
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: UUID | None = None
    attached_image_id: UUID | None = None
    attached_document_id: str | None = None


class ChatFeedback(BaseModel):
    """User feedback on a response."""
    message_id: UUID
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None


# ── Responses ────────────────────────────────────────────


class SourceReference(BaseModel):
    """A reference to a source chunk used in the answer."""
    document_id: str
    document_name: str
    chunk_index: int
    text: str
    relevance_score: float


class ReasoningStep(BaseModel):
    """A single step in the chain-of-thought reasoning."""
    step: int
    title: str
    description: str
    status: str = "pending"  # pending | running | done


class ChatMessageResponse(BaseModel):
    """A single chat message."""
    id: UUID
    role: str
    content: str
    sources: dict | list | None = None
    reasoning_steps: list | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionResponse(BaseModel):
    """High-level session info."""
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ChatStreamChunk(BaseModel):
    """One chunk of a streamed response (sent over SSE)."""
    type: str  # "token" | "source" | "reasoning" | "done" | "error"
    content: str = ""
    sources: list[SourceReference] | None = None
    reasoning_steps: list[ReasoningStep] | None = None
    session_id: UUID | None = None
    message_id: UUID | None = None
