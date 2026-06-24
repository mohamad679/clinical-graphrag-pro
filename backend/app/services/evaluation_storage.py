"""
DB-first storage helpers for internal evaluation runs, baselines, and reviews.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationRun

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvaluationStorageService:
    def _metadata(self, run: EvaluationRun) -> dict[str, Any]:
        return dict(run.metadata_ or {})

    async def save_evaluation(
        self,
        db: AsyncSession,
        evaluation_type: str,
        metrics: dict[str, Any],
        dataset_size: int,
        metadata: dict[str, Any] | None = None,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        commit: bool = True,
    ) -> EvaluationRun:
        run = EvaluationRun(
            evaluation_type=evaluation_type,
            tenant_id=tenant_id,
            user_id=user_id,
            metrics=metrics,
            dataset_size=dataset_size,
            metadata_=metadata or {},
        )
        db.add(run)
        await db.flush()
        if commit:
            await db.commit()
            await db.refresh(run)
        return run

    async def get_run(self, db: AsyncSession, run_id: str | UUID) -> EvaluationRun | None:
        return await db.get(EvaluationRun, UUID(str(run_id)))

    async def list_runs(
        self,
        db: AsyncSession,
        *,
        evaluation_type: str | None = None,
        evaluation_types: Sequence[str] | None = None,
        limit: int = 20,
    ) -> list[EvaluationRun]:
        query = select(EvaluationRun)
        if evaluation_types:
            query = query.where(EvaluationRun.evaluation_type.in_(list(evaluation_types)))
        elif evaluation_type:
            query = query.where(EvaluationRun.evaluation_type == evaluation_type)
        result = await db.execute(query.order_by(desc(EvaluationRun.timestamp)).limit(max(limit, 1)))
        return result.scalars().all()

    async def get_latest_run(
        self,
        db: AsyncSession,
        *,
        evaluation_type: str | None = None,
        evaluation_types: Sequence[str] | None = None,
    ) -> EvaluationRun | None:
        runs = await self.list_runs(
            db,
            evaluation_type=evaluation_type,
            evaluation_types=evaluation_types,
            limit=1,
        )
        return runs[0] if runs else None

    async def get_latest_baseline(
        self,
        db: AsyncSession,
        *,
        evaluation_type: str | None = None,
        evaluation_types: Sequence[str] | None = None,
    ) -> EvaluationRun | None:
        runs = await self.list_runs(
            db,
            evaluation_type=evaluation_type,
            evaluation_types=evaluation_types,
            limit=100,
        )
        for run in runs:
            baseline = (run.metadata_ or {}).get("baseline") or {}
            if baseline.get("is_blessed"):
                return run
        return None

    async def bless_as_baseline(
        self,
        db: AsyncSession,
        *,
        run_id: str | UUID,
        user_id: str,
        note: str | None = None,
        evaluation_type: str | None = None,
    ) -> EvaluationRun:
        run = await self.get_run(db, run_id)
        if run is None:
            raise ValueError(f"Evaluation run {run_id} not found")

        if evaluation_type:
            previous = await self.get_latest_baseline(db, evaluation_type=evaluation_type)
            if previous is not None and previous.id != run.id:
                previous_metadata = self._metadata(previous)
                previous_baseline = dict(previous_metadata.get("baseline") or {})
                previous_baseline["is_blessed"] = False
                previous_metadata["baseline"] = previous_baseline
                previous.metadata_ = previous_metadata

        metadata = self._metadata(run)
        baseline = dict(metadata.get("baseline") or {})
        baseline.update(
            {
                "is_blessed": True,
                "blessed_at": _utcnow(),
                "blessed_by_user_id": user_id,
                "note": note,
            }
        )
        metadata["baseline"] = baseline
        run.metadata_ = metadata
        await db.commit()
        await db.refresh(run)
        return run

    async def record_case_review(
        self,
        db: AsyncSession,
        *,
        run_id: str | UUID,
        case_id: str,
        accepted: bool,
        reviewer_id: str,
        reviewer_role: str,
        tags: list[str] | None = None,
        notes: str | None = None,
        correction_action: str | None = None,
    ) -> EvaluationRun:
        run = await self.get_run(db, run_id)
        if run is None:
            raise ValueError(f"Evaluation run {run_id} not found")

        metadata = self._metadata(run)
        cases = list(metadata.get("case_results") or [])
        updated = False
        review_payload = {
            "accepted": accepted,
            "reviewer_id": reviewer_id,
            "reviewer_role": reviewer_role,
            "tags": list(tags or []),
            "notes": notes,
            "correction_action": correction_action,
            "reviewed_at": _utcnow(),
        }
        for case in cases:
            if case.get("case_id") != case_id:
                continue
            case["human_review"] = review_payload
            case["clinician_acceptance"] = 1.0 if accepted else 0.0
            updated = True
            break

        if not updated:
            raise ValueError(f"Case {case_id} not found on evaluation run {run_id}")

        reviewed_cases = [case for case in cases if case.get("human_review")]
        accepted_cases = [case for case in reviewed_cases if case["human_review"].get("accepted")]
        review_summary = {
            "reviewed_cases": len(reviewed_cases),
            "accepted_cases": len(accepted_cases),
            "acceptance_rate": round(len(accepted_cases) / max(len(reviewed_cases), 1), 3),
            "last_reviewed_at": review_payload["reviewed_at"],
        }
        metadata["case_results"] = cases
        metadata["review_summary"] = review_summary
        run.metadata_ = metadata

        metrics = dict(run.metrics or {})
        if reviewed_cases:
            metrics["clinician_acceptance_rate"] = review_summary["acceptance_rate"]
        run.metrics = metrics

        await db.commit()
        await db.refresh(run)
        return run


evaluation_storage_service = EvaluationStorageService()
