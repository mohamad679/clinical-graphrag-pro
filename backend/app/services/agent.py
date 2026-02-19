"""
Agent Orchestrator Service.
Manages the lifecycle of an agentic workflow: Plan -> Execute -> Reflect.
"""

import json
import logging
import uuid
import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator, Any

from sqlalchemy import update

from app.core.database import async_session_factory
from app.models.workflow import Workflow, WorkflowStep, ToolCall
from app.services.llm import llm_service
from app.services.tool_registry import tool_registry

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """
    Orchestrates the agentic workflow:
    1. Plan: Ask LLM to break down the user query into steps using available tools.
    2. Execute: Run each step, executing tools as needed.
    3. Reflect: Synthesize the results into a final answer.
    """

    async def run(
        self,
        query: str,
        workflow_type: str = "general",
        image_id: str | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Run the agent workflow and yield SSE events.
        """
        workflow_id = uuid.uuid4()
        
        # ── 1. Init Workflow in DB ───────────────────────
        async with async_session_factory() as db:
            workflow = Workflow(
                id=workflow_id,
                session_id=uuid.UUID(session_id) if session_id else None,
                workflow_type=workflow_type,
                status="running",
                input_data={"query": query, "image_id": image_id},
            )
            db.add(workflow)
            await db.commit()

        yield {
            "type": "workflow_start",
            "workflow_id": str(workflow_id),
            "status": "running",
        }

        try:
            # ── 2. PLAN ──────────────────────────────────
            yield {
                "type": "reasoning",
                "step": 0,
                "title": "Planning workflow",
                "description": "Analyzing request and selecting tools...",
                "status": "running",
            }

            tools_def = tool_registry.get_definitions()
            plan = await self._generate_plan(query, tools_def)
            
            yield {
                "type": "reasoning",
                "step": 0,
                "title": "Planning workflow",
                "description": f"Created {len(plan)} steps.",
                "status": "done",
            }

            results_accumulated = []

            # ── 3. EXECUTE ───────────────────────────────
            for i, step_def in enumerate(plan, 1):
                step_title = step_def.get("title", f"Step {i}")
                step_desc = step_def.get("description", "")
                tool_name = step_def.get("tool")
                
                # Update UI: Step started
                yield {
                    "type": "reasoning",
                    "step": i,
                    "title": step_title,
                    "description": step_desc,
                    "status": "running",
                }

                # Create Step in DB
                step_id = uuid.uuid4()
                async with async_session_factory() as db:
                    step_obj = WorkflowStep(
                        id=step_id,
                        workflow_id=workflow_id,
                        step_number=i,
                        title=step_title,
                        description=step_desc,
                        status="running",
                        started_at=datetime.now(timezone.utc),
                    )
                    db.add(step_obj)
                    await db.commit()

                step_result = None
                status = "done"

                if tool_name:
                    params = step_def.get("parameters", {})
                    
                    # Log tool call (persisted later)
                    tool_call_id = uuid.uuid4()
                    
                    yield {
                        "type": "tool_call",
                        "tool": tool_name,
                        "status": "running",
                        "input": params
                    }
                    
                    start_time = datetime.now(timezone.utc)
                    try:
                        step_result = await tool_registry.execute(tool_name, params)
                        status = "completed"
                        error_msg = None
                    except Exception as e:
                        step_result = {"error": str(e)}
                        status = "failed"
                        error_msg = str(e)
                    end_time = datetime.now(timezone.utc)
                    duration = int((end_time - start_time).total_seconds() * 1000)

                    # Persist Tool Call
                    async with async_session_factory() as db:
                        tc = ToolCall(
                            id=tool_call_id,
                            step_id=step_id,
                            tool_name=tool_name,
                            input_data=params,
                            output_data=step_result,
                            duration_ms=duration,
                            status=status,
                        )
                        db.add(tc)
                        await db.commit()

                    yield {
                        "type": "tool_call",
                        "tool": tool_name,
                        "status": "done" if status == "completed" else "error",
                        "output": step_result,
                        "duration": duration
                    }

                # Update Step in DB
                async with async_session_factory() as db:
                    await db.execute(
                        update(WorkflowStep)
                        .where(WorkflowStep.id == step_id)
                        .values(
                            status="done",
                            result=step_result,
                            completed_at=datetime.now(timezone.utc)
                        )
                    )
                    await db.commit()
                
                results_accumulated.append(f"Step {i} ({step_title}): {json.dumps(step_result)}")

                # Update UI: Step done
                yield {
                    "type": "reasoning",
                    "step": i,
                    "title": step_title,
                    "description": "Completed.",
                    "status": "done",
                }

            # ── 4. REFLECT (Synthesis) ───────────────────
            yield {
                "type": "reasoning",
                "step": len(plan) + 1,
                "title": "Synthesizing answer",
                "description": "Generating final response...",
                "status": "running",
            }
            
            final_context = "\n\n".join(results_accumulated)
            
            # Stream the final answer
            full_response = []
            try:
                async for token in llm_service.generate_stream(
                    user_message=query,
                    context=f"The following are results from executed clinical tools to answer the user's query.\n\nWorkflow Execution Results:\n{final_context}",
                ):
                    full_response.append(token)
                    yield {"type": "token", "content": token}
            except Exception as e:
                logger.error(f"Synthesis failed: {e}")
                yield {"type": "error", "content": "Failed to generate synthesis."}

            yield {
                "type": "reasoning",
                "step": len(plan) + 1,
                "title": "Synthesizing answer",
                "description": "Done.",
                "status": "done",
            }

            # Update Workflow in DB
            async with async_session_factory() as db:
                await db.execute(
                    update(Workflow)
                    .where(Workflow.id == workflow_id)
                    .values(
                        status="completed",
                        output_data={"answer": "".join(full_response)},
                        completed_at=datetime.now(timezone.utc)
                    )
                )
                await db.commit()

            yield {"type": "workflow_done", "workflow_id": str(workflow_id)}

        except Exception as e:
            logger.error(f"Workflow failed: {e}", exc_info=True)
            async with async_session_factory() as db:
                await db.execute(
                    update(Workflow)
                    .where(Workflow.id == workflow_id)
                    .values(
                        status="failed",
                        error_message=str(e),
                        completed_at=datetime.now(timezone.utc)
                    )
                )
                await db.commit()
            yield {"type": "error", "content": str(e)}

    async def _generate_plan(self, query: str, tools_def: list[dict]) -> list[dict]:
        """
        Ask LLM to generate a plan.
        Returns a list of steps, each with 'title', 'description', 'tool', 'parameters'.
        """
        prompt = f"""
You are a planner for a clinical AI agent.
User Query: "{query}"

Available Tools:
{json.dumps(tools_def, indent=2)}

Create a step-by-step plan to answer the query.
 each step MUST be a necessary action to answer the user query.
If the query is simple (e.g. "hi"), just plan one step with NO tool.

Output strictly a JSON object with this structure:
{{
  "steps": [
    {{
      "title": "Short title",
      "description": "Explanation",
      "tool": "tool_name_or_null",
      "parameters": {{ "param_name": "value" }}
    }}
  ]
}}
Do not include markdown blocks. Just the raw JSON.
"""
        try:
            response_text = await llm_service.generate(prompt)
            # Cleanup potential markdown fences
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_text)
            return data.get("steps", [])
        except Exception as e:
            logger.error(f"Failed to generate plan: {e}")
            # Fallback plan
            return [{
                "title": "Search Documents",
                "description": "Fallback: Searching medical documents.",
                "tool": "search_documents",
                "parameters": {"query": query}
            }]


agent_orchestrator = AgentOrchestrator()
