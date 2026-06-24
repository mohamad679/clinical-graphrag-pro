"""
Ad hoc internal evaluation endpoints for single-query inspection.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import User, require_role
from app.core.database import get_db
from app.core.retrieval_scope import retrieval_scope_for_user
from app.models.evaluation import EvaluationRun
from app.services.evaluation import evaluation_service
from app.services.evaluation_storage import evaluation_storage_service
from app.services.rag import rag_service

router = APIRouter(prefix="/eval", tags=["Evaluation"])
evaluation_user = require_role("physician")
SINGLE_RESPONSE_EVAL_TYPE = "single_response_eval"
LEGACY_SINGLE_RESPONSE_EVAL_TYPE = "single_query"


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
    answer_groundedness: MetricScore
    citation_correctness: MetricScore
    retrieval_precision: MetricScore
    retrieval_recall_proxy: MetricScore
    clinician_acceptance_rate: MetricScore
    hallucination_rate: MetricScore
    faithfulness: MetricScore
    relevance: MetricScore
    citation_accuracy: MetricScore
    context_precision: MetricScore
    context_recall: MetricScore
    overall_score: float
    created_at: str


class EvalHistoryResponse(BaseModel):
    evaluations: list[EvalRunResponse]
    total: int


def _serialize_eval_row(row: EvaluationRun) -> dict[str, Any]:
    metadata = dict(row.metadata_ or {})
    details = metadata.get("details") or {}
    metrics = dict(row.metrics or {})
    return {
        "id": str(row.id),
        "query": metadata.get("query", ""),
        "answer": metadata.get("answer", ""),
        "answer_groundedness": details.get(
            "answer_groundedness",
            {"score": metrics.get("answer_groundedness", metrics.get("faithfulness", 0.0)), "explanation": ""},
        ),
        "citation_correctness": details.get(
            "citation_correctness",
            {"score": metrics.get("citation_correctness", metrics.get("citation_accuracy", 0.0)), "explanation": ""},
        ),
        "retrieval_precision": details.get(
            "retrieval_precision",
            {"score": metrics.get("retrieval_precision", metrics.get("context_precision", 0.0)), "explanation": ""},
        ),
        "retrieval_recall_proxy": details.get(
            "retrieval_recall_proxy",
            {"score": metrics.get("retrieval_recall_proxy", metrics.get("context_recall", 0.0)), "explanation": ""},
        ),
        "clinician_acceptance_rate": details.get(
            "clinician_acceptance_rate",
            {"score": metrics.get("clinician_acceptance_rate", 0.0), "explanation": ""},
        ),
        "hallucination_rate": details.get(
            "hallucination_rate",
            {"score": metrics.get("hallucination_rate", 0.0), "explanation": ""},
        ),
        "faithfulness": details.get(
            "faithfulness",
            {"score": metrics.get("faithfulness", metrics.get("answer_groundedness", 0.0)), "explanation": ""},
        ),
        "relevance": details.get(
            "relevance",
            {"score": metrics.get("relevance", metrics.get("answer_relevancy", 0.0)), "explanation": ""},
        ),
        "citation_accuracy": details.get(
            "citation_accuracy",
            {"score": metrics.get("citation_accuracy", metrics.get("citation_correctness", 0.0)), "explanation": ""},
        ),
        "context_precision": details.get(
            "context_precision",
            {"score": metrics.get("context_precision", metrics.get("retrieval_precision", 0.0)), "explanation": ""},
        ),
        "context_recall": details.get(
            "context_recall",
            {"score": metrics.get("context_recall", metrics.get("retrieval_recall_proxy", 0.0)), "explanation": ""},
        ),
        "overall_score": float(metrics.get("overall_score", 0.0)),
        "created_at": row.timestamp.isoformat(),
    }


@router.post("/run", response_model=EvalRunResponse)
async def run_evaluation(
    request: EvalRunRequest,
    user: User = Depends(evaluation_user),
    db: AsyncSession = Depends(get_db),
):
    """Run a single ad hoc grounded-response evaluation against the live RAG path."""
    scope = retrieval_scope_for_user(user)
    tenant_id = scope.tenant_id
    result = await rag_service.query(request.query, top_k=request.top_k, scope=scope)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["answer"])

    answer = result["answer"]
    sources = result.get("sources", [])
    context_chunks = [
        {
            "chunk_id": s.get("chunk_id"),
            "citation_id": s.get("citation_id"),
            "chunk_text": s.get("text", ""),
            "document_name": s.get("document_name", ""),
            "document_id": s.get("document_id", ""),
            "chunk_index": s.get("chunk_index", 0),
            "page_start": s.get("page_start"),
            "page_end": s.get("page_end"),
        }
        for s in sources
    ]

    eval_result = await evaluation_service.evaluate(
        query=request.query,
        answer=answer,
        context_chunks=context_chunks,
        sources=sources,
    )

    created_at = datetime.now(timezone.utc).isoformat()
    eval_id = str(uuid.uuid4())
    response_payload = {
        "id": eval_id,
        "query": request.query,
        "answer": answer[:500],
        "answer_groundedness": eval_result.details["answer_groundedness"],
        "citation_correctness": eval_result.details["citation_correctness"],
        "retrieval_precision": eval_result.details["retrieval_precision"],
        "retrieval_recall_proxy": eval_result.details["retrieval_recall_proxy"],
        "clinician_acceptance_rate": eval_result.details["clinician_acceptance_rate"],
        "hallucination_rate": eval_result.details["hallucination_rate"],
        "faithfulness": eval_result.details["faithfulness"],
        "relevance": eval_result.details["relevance"],
        "citation_accuracy": eval_result.details["citation_accuracy"],
        "context_precision": eval_result.details["context_precision"],
        "context_recall": eval_result.details["context_recall"],
        "overall_score": eval_result.overall_score,
        "created_at": created_at,
    }

    await evaluation_storage_service.save_evaluation(
        db=db,
        evaluation_type=SINGLE_RESPONSE_EVAL_TYPE,
        metrics=eval_result.metric_payload(),
        dataset_size=len(context_chunks),
        metadata={
            "query": request.query,
            "answer": answer[:500],
            "details": response_payload,
            "source_count": len(sources),
        },
        tenant_id=tenant_id,
        user_id=user.id,
    )

    return EvalRunResponse(**response_payload)


@router.get("/history", response_model=EvalHistoryResponse)
async def get_eval_history(
    limit: int = 20,
    offset: int = 0,
    include_global: bool = False,
    user: User = Depends(evaluation_user),
    db: AsyncSession = Depends(get_db),
):
    """Return past single-response evaluations from durable storage."""
    if include_global and user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    tenant_id = user.tenant_id or user.id
    query = (
        select(EvaluationRun)
        .where(EvaluationRun.evaluation_type.in_([SINGLE_RESPONSE_EVAL_TYPE, LEGACY_SINGLE_RESPONSE_EVAL_TYPE]))
        .order_by(desc(EvaluationRun.timestamp))
        .offset(offset)
        .limit(limit)
    )
    total_query = select(func.count()).select_from(EvaluationRun).where(
        EvaluationRun.evaluation_type.in_([SINGLE_RESPONSE_EVAL_TYPE, LEGACY_SINGLE_RESPONSE_EVAL_TYPE])
    )
    if not include_global:
        if user.role == "admin":
            query = query.where(EvaluationRun.tenant_id == tenant_id)
            total_query = total_query.where(EvaluationRun.tenant_id == tenant_id)
        else:
            query = query.where(
                EvaluationRun.tenant_id == tenant_id,
                EvaluationRun.user_id == user.id,
            )
            total_query = total_query.where(
                EvaluationRun.tenant_id == tenant_id,
                EvaluationRun.user_id == user.id,
            )
    rows = (await db.execute(query)).scalars().all()
    total = int((await db.execute(total_query)).scalar() or 0)
    return EvalHistoryResponse(
        evaluations=[EvalRunResponse(**_serialize_eval_row(row)) for row in rows],
        total=total,
    )
