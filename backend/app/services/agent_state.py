from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict):
    query: str
    workflow_type: str
    image_id: str | None
    session_id: str | None
    user_id: str | None
    tenant_id: str | None
    plan: list[dict]
    current_step: int
    tool_results: list[dict]
    synthesis: str
    verification_passed: bool | None
    final_answer: str
    events: list[dict]
    error: str | None
    workflow_id: str
    patient_id: str | None
    failure_code: str | None


class ToolCallResult(TypedDict):
    tool_name: str
    params: dict
    result: dict
    success: bool
    latency_ms: float
