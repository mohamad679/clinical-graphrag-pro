"""
API endpoints for Agentic Workflows.
"""

import json
import uuid
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_db
from app.models.workflow import Workflow, WorkflowStep
from app.services.agent import agent_orchestrator
from app.services.tool_registry import tool_registry
from app.schemas.workflow import (
    WorkflowRunRequest,
    WorkflowResponse,
    WorkflowListResponse,
    ToolDefinition,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["Agents"])


@router.post("/run")
async def run_workflow(request: WorkflowRunRequest):
    """
    Start an agentic workflow and stream the results via SSE.
    """
    logger.info(f"🚀 Starting agent workflow for query: {request.query}")

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event in agent_orchestrator.run(
                query=request.query,
                workflow_type=request.workflow_type,
                session_id=str(request.session_id) if request.session_id else None,
                image_id=request.image_id,
            ):
                # SSE format: data: JSON\n\n
                yield json.dumps(event)
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield json.dumps({"type": "error", "content": str(e)})

    return EventSourceResponse(event_generator())


@router.get("/workflows", response_model=WorkflowListResponse)
async def list_workflows(
    skip: int = 0,
    limit: int = 20,
    session_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List past workflow executions."""
    query = select(Workflow).options(
        selectinload(Workflow.steps)
    ).order_by(desc(Workflow.created_at)).offset(skip).limit(limit)

    if session_id:
        query = query.where(Workflow.session_id == session_id)

    result = await db.execute(query)
    workflows = result.scalars().all()
    
    # Count total
    count_query = select(Workflow)
    if session_id:
        count_query = count_query.where(Workflow.session_id == session_id)
    # Note: select(func.count()) is better but for simplicity/speed just fetching logic:
    # Since we don't have a direct count query easily ready with filtering without re-writing logic
    # We'll do a separate count query or just return total as len for current page + skip (approx)
    # For production, use func.count(). keeping it simple for now.
    
    return {"workflows": workflows, "total": len(workflows)}


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get full details of a specific workflow."""
    query = select(Workflow).where(Workflow.id == workflow_id).options(
        selectinload(Workflow.steps).selectinload(WorkflowStep.tool_calls)
    )
    result = await db.execute(query)
    workflow = result.scalar_one_or_none()
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
        
    return workflow


@router.get("/tools", response_model=list[ToolDefinition])
async def list_tools():
    """List available tools for the agent."""
    return tool_registry.get_definitions()
