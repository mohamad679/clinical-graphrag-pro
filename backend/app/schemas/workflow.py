"""
Pydantic schemas for agent workflows and tools.
"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class WorkflowRunRequest(BaseModel):
    """Request to start a new agent workflow."""
    query: str
    workflow_type: str = "general"
    image_id: str | None = None
    session_id: str | None = None
    patient_id: str | None = None


class ToolCallResponse(BaseModel):
    """Response schema for a tool execution."""
    id: UUID
    tool_name: str
    input_data: dict | None = None
    output_data: dict | None = None
    duration_ms: int | None = None
    status: str
    error_message: str | None = None
    timeout_seconds: int | None = None
    metadata: dict | None = Field(default=None, alias="metadata_")
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class WorkflowStepResponse(BaseModel):
    """Response schema for a single workflow step."""
    id: UUID
    step_number: int
    phase: str
    title: str
    description: str | None = None
    status: str
    tool_calls: list[ToolCallResponse] = []
    error_message: str | None = None
    timeout_seconds: int | None = None
    metadata: dict | None = Field(default=None, alias="metadata_")
    result: dict | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class WorkflowResponse(BaseModel):
    """Full workflow response."""
    id: UUID
    job_id: UUID | None = None
    session_id: UUID | None = None
    workflow_type: str
    status: str
    current_phase: str
    timeout_seconds: int | None = None
    input_data: dict | None = None
    metadata: dict | None = Field(default=None, alias="metadata_")
    output_data: dict | None = None
    error_message: str | None = None
    cancel_requested_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    steps: list[WorkflowStepResponse] = []

    model_config = {"from_attributes": True, "populate_by_name": True}


class WorkflowListResponse(BaseModel):
    """List of workflows."""
    workflows: list[WorkflowResponse]
    total: int


class ToolDefinition(BaseModel):
    """Schema for tool discovery."""
    name: str
    description: str
    parameters: dict


# ── Structured Agent Workflow Schemas ─────────────────────

class AgentPlanStep(BaseModel):
    title: str
    description: str
    tool: str | None = None
    parameters: dict = Field(default_factory=dict)


class AgentPlan(BaseModel):
    steps: list[AgentPlanStep]


class EvidenceItem(BaseModel):
    source: str
    text: str
    score: float | None = None


class VerificationResultSchema(BaseModel):
    status: str  # APPROVED, REJECTED, ABSTAINED
    confidence_score: float
    flags: list[str] = Field(default_factory=list)
    failure_code: str | None = None


class FinalAnswer(BaseModel):
    answer: str
    verification: VerificationResultSchema


class WorkflowTraceEvent(BaseModel):
    type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    workflow_id: str
    step: int | None = None
    title: str | None = None
    description: str | None = None
    metadata: dict = Field(default_factory=dict)
