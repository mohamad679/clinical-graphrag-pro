"""
Internal evaluation run, baseline, and human-review endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import User, require_admin, require_role
from app.core.database import get_db
from app.services.evaluation_runner import (
    DEFAULT_QUALITY_BASELINE,
    INTERNAL_EVALUATION_TYPE,
    INTERNAL_SUITE_NAME,
    INTERNAL_SUITE_VERSION,
    QUALITY_EVALUATION_TYPES,
)
from app.services.evaluation_storage import evaluation_storage_service
from app.services.job_state import job_state_service
from app.worker import dispatch_evaluation_run

router = APIRouter(prefix="/evaluations", tags=["Evaluations"])
evaluation_reader = require_role("physician")
evaluation_reviewer = require_role("physician")


class BaselineRequest(BaseModel):
    note: str | None = None


class EvaluationReviewRequest(BaseModel):
    case_id: str
    accepted: bool
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    correction_action: str | None = None


def _metric_aliases(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "faithfulness": metrics.get("faithfulness", metrics.get("answer_groundedness")),
        "answer_relevancy": metrics.get("answer_relevancy", metrics.get("relevance")),
        "context_recall": metrics.get("context_recall", metrics.get("retrieval_recall_proxy")),
        "context_precision": metrics.get("context_precision", metrics.get("retrieval_precision")),
    }


def _format_report(run) -> dict[str, Any]:
    metadata = dict(run.metadata_ or {})
    metrics = dict(run.metrics or {})
    aliases = _metric_aliases(metrics)
    review_summary = metadata.get("review_summary") or {
        "reviewed_cases": 0,
        "accepted_cases": 0,
        "acceptance_rate": metrics.get("clinician_acceptance_rate", 0.0),
        "last_reviewed_at": None,
    }
    baseline = metadata.get("baseline") or {
        "source": "default_thresholds",
        "metrics": dict(DEFAULT_QUALITY_BASELINE),
    }
    return {
        "id": str(run.id),
        "timestamp": run.timestamp.isoformat(),
        "evaluation_type": run.evaluation_type,
        "suite_name": metadata.get("suite_name", INTERNAL_SUITE_NAME),
        "suite_version": metadata.get("suite_version", INTERNAL_SUITE_VERSION),
        "dataset_size": run.dataset_size,
        "runner": metadata.get("runner", "internal_quality_suite"),
        "status": metadata.get("status", "completed"),
        "metrics": metrics,
        "cases": metadata.get("case_results", []),
        "category_breakdown": metadata.get("category_breakdown", {}),
        "quality_gate": metadata.get("quality_gate", {}),
        "baseline": baseline,
        "review_summary": review_summary,
        "job_id": metadata.get("job_id"),
        **aliases,
    }


@router.post("/run")
async def run_evaluation(
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Dispatch the internal product-quality suite."""
    job = await job_state_service.create_job(
        db,
        job_type="evaluation_run",
        entity_type="evaluation",
        payload={
            "evaluation_type": INTERNAL_EVALUATION_TYPE,
            "suite_name": INTERNAL_SUITE_NAME,
            "suite_version": INTERNAL_SUITE_VERSION,
        },
    )
    job_id = str(job.id)
    await db.commit()
    await dispatch_evaluation_run(job_id)
    return {
        "status": "started",
        "job_id": job_id,
        "evaluation_type": INTERNAL_EVALUATION_TYPE,
        "suite_name": INTERNAL_SUITE_NAME,
    }


@router.get("/metrics")
async def get_evaluation_metrics(
    limit: int = 20,
    _user: User = Depends(evaluation_reader),
    db: AsyncSession = Depends(get_db),
):
    """Return recent internal evaluation history for trend charts."""
    runs = await evaluation_storage_service.list_runs(
        db,
        evaluation_types=QUALITY_EVALUATION_TYPES,
        limit=limit,
    )
    return {
        "source": "database",
        "data": [_format_report(run) for run in runs],
    }


@router.get("/latest")
async def get_latest_evaluation(
    _user: User = Depends(evaluation_reader),
    db: AsyncSession = Depends(get_db),
):
    """Return the latest internal evaluation report."""
    run = await evaluation_storage_service.get_latest_run(
        db,
        evaluation_types=QUALITY_EVALUATION_TYPES,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="No evaluation report available yet.")
    return _format_report(run)


@router.get("/baseline")
async def get_blessed_baseline(
    _user: User = Depends(evaluation_reader),
    db: AsyncSession = Depends(get_db),
):
    """Return the latest blessed evaluation baseline, if one exists."""
    run = await evaluation_storage_service.get_latest_baseline(
        db,
        evaluation_types=QUALITY_EVALUATION_TYPES,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="No blessed baseline is available yet.")
    return _format_report(run)


@router.post("/{run_id}/baseline")
async def bless_evaluation_baseline(
    run_id: str,
    request: BaselineRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Bless an evaluation run as the current release baseline."""
    run = await evaluation_storage_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    saved = await evaluation_storage_service.bless_as_baseline(
        db,
        run_id=run_id,
        user_id=user.id,
        note=request.note,
        evaluation_type=run.evaluation_type,
    )
    return _format_report(saved)


@router.post("/{run_id}/review")
async def review_evaluation_case(
    run_id: str,
    request: EvaluationReviewRequest,
    user: User = Depends(evaluation_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """Record physician/admin review for a specific evaluation case."""
    try:
        saved = await evaluation_storage_service.record_case_review(
            db,
            run_id=run_id,
            case_id=request.case_id,
            accepted=request.accepted,
            reviewer_id=user.id,
            reviewer_role=user.role,
            tags=request.tags,
            notes=request.notes,
            correction_action=request.correction_action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _format_report(saved)
