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

            # ── 4. REFLECT (Synthesis & Verification) ───────────────────
            yield {
                "type": "reasoning",
                "step": len(plan) + 1,
                "title": "Drafting Response",
                "description": "Synthesizing tools and generating initial draft...",
                "status": "running",
            }
            
            final_context = "\n\n".join(results_accumulated)
            
            # Generate the draft internally (no streaming yet)
            draft_prompt = f"The following are results from executed clinical tools to answer the user's query: '{query}'.\n\nWorkflow Execution Results:\n{final_context}\n\nProvide the final clinical answer."
            
            try:
                draft_response = await llm_service.generate(draft_prompt)
            except Exception as e:
                logger.error(f"Draft generation failed: {e}")
                draft_response = "Failed to generate initial draft."

            yield {
                "type": "reasoning",
                "step": len(plan) + 1,
                "title": "Drafting Response",
                "description": "Draft complete.",
                "status": "done",
            }

            # ── 5. ADJUDICATE (Red Team Eval) ──────────────────────────
            yield {
                "type": "reasoning",
                "step": len(plan) + 2,
                "title": "Calibration & Verification",
                "description": "Adjudicator is reviewing draft for hallucinations and safety...",
                "status": "running",
            }

            eval_result = await tool_registry.execute(
                "clinical_eval", 
                {"proposed_answer": draft_response, "source_context": final_context}
            )

            status = eval_result.get("status", "REJECTED")
            flags = eval_result.get("flags", [])

            yield {
                "type": "verification",
                "status": status,
                "flags": flags,
                "confidence_score": eval_result.get("confidence_score", 0.0)
            }

            if status == "APPROVED":
                final_answer = draft_response
                # Simulate streaming the approved text to the frontend
                for chunk in [final_answer[i:i+50] for i in range(0, len(final_answer), 50)]:
                    yield {"type": "token", "content": chunk}
                    await asyncio.sleep(0.05)
            else:
                final_answer = f"⚠️ **Safety Adjudicator Intercepted Response:**\n\nI apologize, but I am unable to provide the drafted clinical response. The internal Red Team safety evaluator flagged the draft for the following reasons:\n\n"
                for flag in flags:
                    final_answer += f"- {flag}\n"
                final_answer += "\nPlease resubmit your query or rely on primary medical literature."
                
                # Stream the rejection text
                for chunk in [final_answer[i:i+50] for i in range(0, len(final_answer), 50)]:
                    yield {"type": "token", "content": chunk}
                    await asyncio.sleep(0.05)

            yield {
                "type": "reasoning",
                "step": len(plan) + 2,
                "title": "Calibration & Verification",
                "description": f"Verification Status: {status}",
                "status": "done",
            }

            # Update Workflow in DB
            async with async_session_factory() as db:
                await db.execute(
                    update(Workflow)
                    .where(Workflow.id == workflow_id)
                    .values(
                        status="completed",
                        output_data={"answer": final_answer, "verification": eval_result},
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
        Act as the Supervisor Agent. Determine which sub-agents to invoke.
        Returns a list of steps, where the 'tool' might be a sub-agent invocation or a direct tool.
        """
        supervisor_prompt = f"""
You are the **Supervisor Agent** for Clinical GraphRAG Pro.
User Query: "{query}"

You have the following Expert Sub-Agents available:
1. **DataExtractionAgent**: Extracts structured data (vitals, meds, history) from raw text. DOES NOT use external medical tools.
2. **PharmacovigilanceAgent**: Specializes in checking drug-drug interactions and adverse events using the Graph.
3. **DiagnosticsAgent**: Specializes in differential diagnosis based on symptoms.

You also have direct access to these basic tools:
{json.dumps([t for t in tools_def if t['name'] not in ('search_graph', 'drug_interaction')], indent=2)}

Create a step-by-step plan to answer the query. You can delegate tasks to the sub-agents by using their name as the 'tool', or use the basic tools directly.
If delegating to a sub-agent, provide specific instructions in the parameters.

Output strictly a JSON object with this structure:
{{
  "steps": [
    {{
      "title": "Short title",
      "description": "Explanation",
      "agent": "SubAgentName or null",
      "tool": "tool_name_or_null",
      "parameters": {{ "param_name": "value" }}
    }}
  ]
}}
Do not include markdown blocks. Just the raw JSON.
"""
        try:
            response_text = await llm_service.generate(supervisor_prompt)
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_text)
            
            # Map the new 'agent' delegation back to the 'tool' execution pipeline for seamless frontend streaming
            steps = data.get("steps", [])
            for step in steps:
                if step.get("agent"):
                    step["tool"] = f"delegate_to_{step['agent']}"
            return steps
        except Exception as e:
            logger.error(f"Failed to generate supervisor plan: {e}")
            return [{
                "title": "Search Documents",
                "description": "Fallback: Searching medical documents.",
                "tool": "search_documents",
                "parameters": {"query": query}
            }]


# ── Sub-Agent Handlers (Worker Nodes) ──────────────────────
# These act as specialized tools the Supervisor can call

async def run_data_extraction_agent(parameters: dict) -> dict:
    prompt = f"You are the Data Extraction Agent. Extract JSON structured data from this input: {parameters}\nOutput ONLY JSON."
    res = await llm_service.generate(prompt)
    return {"extracted_data": res}

async def run_pharmacovigilance_agent(parameters: dict) -> dict:
    # This agent would hypothetically chain the drug tools. For Phase 2, we simulate the specific tool call.
    drug = parameters.get("drug", parameters.get("param_name", "Unknown Medicine"))
    res = await tool_registry.execute("drug_interaction", {"drug_name": drug})
    return {"pharmacovigilance_report": res}

async def run_diagnostics_agent(parameters: dict) -> dict:
    prompt = f"You are the Diagnostics Agent. Given these symptoms, output a JSON list of differential diagnoses with probabilities: {parameters}"
    res = await llm_service.generate(prompt)
    return {"differentials": res}

# Register sub-agents as internal tools so the orchestrator can execute them via the existing loop
@tool_registry.register(name="delegate_to_DataExtractionAgent", description="Internal routing", parameters={})
async def _extract(**kwargs): return await run_data_extraction_agent(kwargs)

@tool_registry.register(name="delegate_to_PharmacovigilanceAgent", description="Internal routing", parameters={})
async def _pharmaco(**kwargs): return await run_pharmacovigilance_agent(kwargs)

@tool_registry.register(name="delegate_to_DiagnosticsAgent", description="Internal routing", parameters={})
async def _diagnostic(**kwargs): return await run_diagnostics_agent(kwargs)



agent_orchestrator = AgentOrchestrator()
