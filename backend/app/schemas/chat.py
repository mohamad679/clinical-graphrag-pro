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
    attached_document_id: UUID | None = None


class ChatFeedback(BaseModel):
    """User feedback on a response."""
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None


# ── Responses ────────────────────────────────────────────


class SourceReference(BaseModel):
    """A reference to a source chunk used in the answer."""
    citation_id: str | None = None
    chunk_id: str | None = None
    document_id: str
    document_name: str
    chunk_index: int
    text: str | None = Field(
        default=None,
        description="Deprecated. Browser responses omit raw chunk text; use chunk_id/document_id for lookup.",
    )
    relevance_score: float
    page_reference: str | None = None
    page_start: int | None = None
    page_end: int | None = None


class CitationReference(BaseModel):
    """Inline citation occurrence mapped back to a grounded chunk."""
    marker: str
    chunk_id: str
    document_id: str
    document_name: str
    page_reference: str | None = None
    span_start: int
    span_end: int


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
    heuristic_evidence_support_score: float | None = None
    confidence_score: float | None = None
    metadata: dict | None = None
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
    citations: list[CitationReference] | None = None
    reasoning_steps: list[ReasoningStep] | None = None
    session_id: UUID | None = None
    message_id: UUID | None = None
    trace: dict | None = None


class ChatSyncResponse(BaseModel):
    answer: str
    sources: list[SourceReference] = Field(default_factory=list)
    citations: list[CitationReference] = Field(default_factory=list)
    reasoning_steps: list[ReasoningStep] | list[dict] = Field(default_factory=list)
    trace: dict = Field(default_factory=dict)
    session_id: str
    message_id: str
    heuristic_evidence_support_score: float | None = Field(
        default=None,
        description="Heuristic evidence-support score, not calibrated clinical confidence.",
    )
    confidence_score: float | None = None
    confidence_score_deprecated: bool = True
    model_used: str | None = None
    clinician_review_required: bool = True
    error: bool = False
