"""
Evaluation API endpoints.
Provides REST endpoints for evaluating RAG quality and retrieving eval history.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.evaluation import evaluation_service
from app.services.rag import rag_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/eval", tags=["Evaluation"])

# ── In-memory eval history (persisted in prod via DB) ────

_eval_history: list[dict] = []


# ── Schemas ──────────────────────────────────────────────

class EvalRunRequest(BaseModel):
    query: str
    top_k: int = 5


class MetricScore(BaseModel):
    score: float
    explanation: str


class EvalRunResponse(BaseModel):
    id: str
    query: str
    answer: str
    faithfulness: MetricScore
    relevance: MetricScore
    citation_accuracy: MetricScore
    context_precision: MetricScore
    overall_score: float
    created_at: str


class EvalHistoryResponse(BaseModel):
    evaluations: list[EvalRunResponse]
    total: int


# ── Endpoints ────────────────────────────────────────────

@router.post("/run", response_model=EvalRunResponse)
async def run_evaluation(request: EvalRunRequest):
    """
    Run a RAG query and evaluate the result.
    Returns quality metrics for the retrieval + generation.
    """
    try:
        # 1. Run the RAG pipeline
        result = await rag_service.query(request.query, top_k=request.top_k)

        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["answer"])

        answer = result["answer"]
        sources = result.get("sources", [])

        # Build context chunks from sources
        context_chunks = [
            {
                "chunk_text": s.get("text", ""),
                "document_name": s.get("document_name", ""),
                "document_id": s.get("document_id", ""),
                "chunk_index": s.get("chunk_index", 0),
            }
            for s in sources
        ]

        # 2. Evaluate
        eval_result = await evaluation_service.evaluate(
            query=request.query,
            answer=answer,
            context_chunks=context_chunks,
            sources=sources,
        )

        # 3. Build response
        eval_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        response = EvalRunResponse(
            id=eval_id,
            query=request.query,
            answer=answer[:500],
            faithfulness=MetricScore(**eval_result.details["faithfulness"]),
            relevance=MetricScore(**eval_result.details["relevance"]),
            citation_accuracy=MetricScore(**eval_result.details["citation_accuracy"]),
            context_precision=MetricScore(**eval_result.details["context_precision"]),
            overall_score=eval_result.overall_score,
            created_at=created_at,
        )

        # Persist to history
        _eval_history.insert(0, response.model_dump())

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", response_model=EvalHistoryResponse)
async def get_eval_history(limit: int = 20, offset: int = 0):
    """Get past evaluation results."""
    total = len(_eval_history)
    evaluations = _eval_history[offset : offset + limit]

    return EvalHistoryResponse(
        evaluations=[EvalRunResponse(**e) for e in evaluations],
        total=total,
    )
