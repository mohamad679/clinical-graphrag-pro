"""
Durable job state helpers for background and long-running tasks.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.observability import export_trace_context
from app.models.persistence import JobRun

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = {"queued", "dispatched", "running", "retry_scheduled", "cancelling"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "dead_lettered"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStateService:
    @staticmethod
    def _normalize_job_id(job_id: str | UUID) -> UUID:
        return UUID(str(job_id))

    @staticmethod
    def _stable_payload_hash(payload: dict[str, Any] | None) -> str:
        serialized = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    async def create_job(
        self,
        db: AsyncSession,
        *,
        job_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        created_by_user_id: str | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: int | None = None,
        timeout_seconds: int | None = None,
        idempotency_key: str | None = None,
        dedupe_active: bool = True,
    ) -> JobRun:
        settings = get_settings()
        payload_hash = self._stable_payload_hash(payload)
        effective_key = idempotency_key or f"{job_type}:{entity_type or ''}:{entity_id or ''}:{payload_hash}"
        trace_context = export_trace_context()

        if dedupe_active:
            result = await db.execute(
                select(JobRun)
                .where(
                    JobRun.job_type == job_type,
                    JobRun.idempotency_key == effective_key,
                    JobRun.status.in_(ACTIVE_JOB_STATUSES),
                )
                .order_by(JobRun.queued_at.desc())
                .limit(1)
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                return existing

        job = JobRun(
            job_type=job_type,
            entity_type=entity_type,
            entity_id=entity_id,
            created_by_user_id=created_by_user_id,
            payload=payload or {},
            payload_hash=payload_hash,
            idempotency_key=effective_key,
            max_retries=max_retries if max_retries is not None else settings.background_job_default_max_retries,
            retry_backoff_seconds=(
                retry_backoff_seconds
                if retry_backoff_seconds is not None
                else settings.background_job_retry_backoff_seconds
            ),
            timeout_seconds=timeout_seconds,
            metadata_={**(metadata or {}), "trace": trace_context},
            status="queued",
            progress=0,
        )
        db.add(job)
        await db.flush()
        logger.info(
            "job.created",
            extra={
                **trace_context,
                "component": "worker",
                "event": "job.created",
                "job_id": str(job.id),
                "task_type": job_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        )
        return job

    async def get_job(self, db: AsyncSession, job_id: str | UUID) -> JobRun | None:
        result = await db.execute(select(JobRun).where(JobRun.id == self._normalize_job_id(job_id)))
        return result.scalar_one_or_none()

    async def update_job(
        self,
        db: AsyncSession,
        job_id: str | UUID,
        *,
        status: str | None = None,
        progress: int | None = None,
        error_message: str | None = None,
        result: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        started: bool = False,
        completed: bool = False,
        increment_attempt: bool = False,
        next_retry_in_seconds: int | None = None,
        worker_task_id: str | None = None,
        dispatched: bool = False,
    ) -> JobRun | None:
        job = await self.get_job(db, job_id)
        if job is None:
            return None

        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = max(0, min(progress, 100))
        if error_message is not None:
            job.error_message = error_message
            job.last_error = error_message
        if result is not None:
            job.result = result
        if metadata is not None:
            merged = dict(job.metadata_ or {})
            merged.update(metadata)
            job.metadata_ = merged
        if worker_task_id is not None:
            job.worker_task_id = worker_task_id
        if dispatched:
            job.dispatched_at = _utcnow()
            if job.status == "queued":
                job.status = "dispatched"
        if started and job.started_at is None:
            job.started_at = _utcnow()
            if job.status in {"queued", "dispatched", "retry_scheduled"}:
                job.status = "running"
        if increment_attempt:
            job.attempt_count += 1
        if next_retry_in_seconds is not None:
            job.next_retry_at = _utcnow() + timedelta(seconds=max(next_retry_in_seconds, 0))
        elif status not in {"retry_scheduled"}:
            job.next_retry_at = None
        if completed:
            job.completed_at = _utcnow()
            if job.status not in TERMINAL_JOB_STATUSES:
                job.status = status or "completed"
        if job.status in TERMINAL_JOB_STATUSES and job.completed_at is None:
            job.completed_at = _utcnow()
        if job.status != "dead_lettered":
            job.dead_lettered_at = None
        await db.flush()
        return job

    async def mark_dispatched(
        self,
        db: AsyncSession,
        job_id: str | UUID,
        *,
        worker_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> JobRun | None:
        return await self.update_job(
            db,
            job_id,
            status="dispatched",
            dispatched=True,
            worker_task_id=worker_task_id,
            metadata=metadata,
        )

    async def mark_retry_scheduled(
        self,
        db: AsyncSession,
        job_id: str | UUID,
        *,
        error_message: str,
        countdown_seconds: int,
        metadata: dict[str, Any] | None = None,
    ) -> JobRun | None:
        return await self.update_job(
            db,
            job_id,
            status="retry_scheduled",
            error_message=error_message,
            metadata=metadata,
            next_retry_in_seconds=countdown_seconds,
        )

    async def mark_dead_lettered(
        self,
        db: AsyncSession,
        job_id: str | UUID,
        *,
        error_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> JobRun | None:
        job = await self.update_job(
            db,
            job_id,
            status="dead_lettered",
            progress=100,
            error_message=error_message,
            metadata=metadata,
            completed=True,
        )
        if job is not None:
            job.dead_lettered_at = _utcnow()
            await db.flush()
        return job

    async def request_cancel(
        self,
        db: AsyncSession,
        job_id: str | UUID,
        *,
        reason: str | None = None,
    ) -> JobRun | None:
        job = await self.get_job(db, job_id)
        if job is None:
            return None
        job.cancel_requested_at = _utcnow()
        if job.status in {"queued", "dispatched", "retry_scheduled"}:
            job.status = "cancelled"
            job.progress = 100
            job.completed_at = _utcnow()
        else:
            job.status = "cancelling"
        if reason:
            meta = dict(job.metadata_ or {})
            meta["cancel_reason"] = reason
            job.metadata_ = meta
        await db.flush()
        return job

    async def is_cancel_requested(self, db: AsyncSession, job_id: str | UUID) -> bool:
        job = await self.get_job(db, job_id)
        return bool(job and job.cancel_requested_at is not None)

    async def should_skip_duplicate_dispatch(self, db: AsyncSession, job_id: str | UUID) -> bool:
        job = await self.get_job(db, job_id)
        if job is None:
            return False
        return job.status in {"dispatched", "running", "retry_scheduled"} and bool(job.worker_task_id)

    def retry_countdown(self, job: JobRun, current_retry: int) -> int:
        settings = get_settings()
        base = max(job.retry_backoff_seconds or settings.background_job_retry_backoff_seconds, 1)
        delay = base * (2 ** max(current_retry, 0))
        return min(delay, settings.background_job_retry_backoff_max_seconds)


job_state_service = JobStateService()
