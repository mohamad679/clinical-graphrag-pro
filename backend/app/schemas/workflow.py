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


class ToolCallResponse(BaseModel):
    """Response schema for a tool execution."""
    id: UUID
    tool_name: str
    input_data: dict | None = None
    output_data: dict | None = None
    duration_ms: int | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowStepResponse(BaseModel):
    """Response schema for a single workflow step."""
    id: UUID
    step_number: int
    title: str
    description: str | None = None
    status: str
    tool_calls: list[ToolCallResponse] = []
    result: dict | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class WorkflowResponse(BaseModel):
    """Full workflow response."""
    id: UUID
    session_id: UUID | None = None
    workflow_type: str
    status: str
    input_data: dict | None = None
    output_data: dict | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    steps: list[WorkflowStepResponse] = []

    model_config = {"from_attributes": True}


class WorkflowListResponse(BaseModel):
    """List of workflows."""
    workflows: list[WorkflowResponse]
    total: int


class ToolDefinition(BaseModel):
    """Schema for tool discovery."""
    name: str
    description: str
    parameters: dict
