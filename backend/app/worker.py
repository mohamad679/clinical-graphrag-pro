"""
Celery worker configuration for durable background jobs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.metrics import observe_celery_task
from app.core.observability import bind_observability_context, export_trace_context, trace_operation
from app.services.audio_processing import process_audio_transcription_async
from app.services.data_retention import purge_expired_sessions
from app.services.document_processing import process_document_async
from app.services.evaluation_runner import evaluation_runner_service
from app.services.fine_tune import fine_tune_service
from app.services.image_processing import process_image_analysis_async
from app.services.job_state import job_state_service

logger = logging.getLogger(__name__)
settings = get_settings()

try:
    from celery import Celery
    from celery.exceptions import SoftTimeLimitExceeded
except Exception:  # pragma: no cover - optional at runtime in local/test envs
    Celery = None  # type: ignore[assignment]
    SoftTimeLimitExceeded = TimeoutError  # type: ignore[assignment]


@dataclass(frozen=True)
class JobSpec:
    task_name: str
    timeout_seconds: int | None


JOB_SPECS = {
    "document_processing": JobSpec(
        task_name="app.worker.process_document_task",
        timeout_seconds=settings.document_processing_timeout_seconds,
    ),
    "evaluation_run": JobSpec(
        task_name="app.worker.run_evaluation_task",
        timeout_seconds=settings.evaluation_timeout_seconds,
    ),
    "image_analysis": JobSpec(
        task_name="app.worker.process_image_analysis_task",
        timeout_seconds=settings.image_analysis_timeout_seconds,
    ),
    "audio_transcription": JobSpec(
        task_name="app.worker.process_audio_transcription_task",
        timeout_seconds=settings.audio_transcription_timeout_seconds,
    ),
    "retention_purge": JobSpec(
        task_name="app.worker.purge_expired_data_task",
        timeout_seconds=settings.evaluation_timeout_seconds,
    ),
    "fine_tune_training": JobSpec(
        task_name="app.worker.fine_tune_training_task",
        timeout_seconds=settings.evaluation_timeout_seconds,
    ),
}


def _background_jobs_required() -> bool:
    return settings.background_jobs_require_broker and not settings.celery_task_always_eager


def _run_document_processing(document_id: str) -> dict:
    return asyncio.run(process_document_async(document_id))


def _run_evaluation(job_id: str) -> dict:
    report = asyncio.run(evaluation_runner_service.run_builtin_evaluation(job_id))
    return {"job_id": job_id, "metrics": report.metrics}


def _run_image_analysis(image_id: str, additional_context: str = "") -> dict:
    return asyncio.run(process_image_analysis_async(image_id, additional_context))


def _run_audio_transcription(transcript_id: str) -> dict:
    return asyncio.run(process_audio_transcription_async(transcript_id))


def _run_retention() -> dict:
    return asyncio.run(purge_expired_sessions())


def _run_fine_tune_training(job_id: str) -> dict:
    return fine_tune_service.run_training_job_sync(job_id)


async def _load_job_state(job_id: str):
    async with async_session_factory() as session:
        job = await job_state_service.get_job(session, job_id)
        return job


async def _mark_job_dispatched(
    job_id: str,
    *,
    worker_task_id: str | None,
    transport: str,
) -> None:
    async with async_session_factory() as session:
        await job_state_service.mark_dispatched(
            session,
            job_id,
            worker_task_id=worker_task_id,
            metadata={"dispatch_transport": transport},
        )
        await session.commit()
    logger.info(
        "job.dispatched",
        extra={
            **export_trace_context(),
            "component": "celery",
            "event": "job.dispatched",
            "job_id": job_id,
            "task_type": transport,
            "worker_task_id": worker_task_id,
        },
    )


async def _check_skip_duplicate_dispatch(job_id: str) -> bool:
    async with async_session_factory() as session:
        return await job_state_service.should_skip_duplicate_dispatch(session, job_id)


async def _cancel_job(job_id: str, *, reason: str) -> None:
    async with async_session_factory() as session:
        await job_state_service.request_cancel(session, job_id, reason=reason)
        await session.commit()


async def _mark_job_failed(job_id: str, *, error_message: str, metadata: dict[str, Any] | None = None) -> None:
    async with async_session_factory() as session:
        await job_state_service.update_job(
            session,
            job_id,
            status="failed",
            progress=100,
            error_message=error_message,
            metadata=metadata,
            completed=True,
        )
        await session.commit()


async def _execute_job_async(
    *,
    job_id: str,
    default_job_type: str,
    runner: Callable[..., dict],
    runner_args: tuple[Any, ...],
    worker_task_id: str | None = None,
) -> dict:
    async with async_session_factory() as session:
        job = await job_state_service.get_job(session, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        trace_context = dict((job.metadata_ or {}).get("trace") or {})
        entity_field_map = {
            "document_processing": {"document_id": job.entity_id},
            "image_analysis": {"image_id": job.entity_id},
            "audio_transcription": {"transcript_id": job.entity_id},
            "evaluation_run": {},
        }
        if job.cancel_requested_at is not None:
            await job_state_service.update_job(
                session,
                job.id,
                status="cancelled",
                progress=100,
                completed=True,
                metadata={"cancelled_before_start": True},
            )
            await session.commit()
            return {"job_id": job_id, "status": "cancelled"}

        await job_state_service.update_job(
            session,
            job.id,
            status="running",
            started=True,
            increment_attempt=True,
            worker_task_id=worker_task_id,
            metadata={"job_type": job.job_type or default_job_type},
        )
        await session.commit()

    task_type = str(job.job_type or default_job_type)
    with bind_observability_context(
        **trace_context,
        job_id=job_id,
        task_type=task_type,
        **entity_field_map.get(task_type, {}),
    ):
        started = time.perf_counter()
        try:
            with trace_operation(
                "worker.execute",
                component="celery",
                logger_=logger,
                task_type=task_type,
                job_id=job_id,
                worker_task_id=worker_task_id,
            ):
                result = await asyncio.to_thread(runner, *runner_args)
        except Exception:
            observe_celery_task(time.perf_counter() - started, task_type=task_type, success=False)
            # The concrete task wrapper owns retry/dead-letter transitions.
            raise
        observe_celery_task(time.perf_counter() - started, task_type=task_type, success=True)

    async with async_session_factory() as session:
        job = await job_state_service.get_job(session, job_id)
        if job is not None and job.status not in {"completed", "failed", "dead_lettered", "cancelled"}:
            await job_state_service.update_job(
                session,
                job.id,
                status="completed",
                progress=100,
                result=result,
                completed=True,
            )
            await session.commit()
    return result


def _execute_job_sync(
    *,
    job_id: str,
    default_job_type: str,
    runner: Callable[..., dict],
    runner_args: tuple[Any, ...],
    worker_task_id: str | None = None,
) -> dict:
    return asyncio.run(
        _execute_job_async(
            job_id=job_id,
            default_job_type=default_job_type,
            runner=runner,
            runner_args=runner_args,
            worker_task_id=worker_task_id,
        )
    )


if Celery is not None:
    try:
        from celery.schedules import crontab
    except Exception:  # pragma: no cover
        crontab = None  # type: ignore[assignment]

    celery_app = Celery(
        "clinical_graphrag",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_always_eager=settings.celery_task_always_eager,
        task_store_eager_result=settings.celery_task_store_eager_result,
        broker_connection_retry_on_startup=True,
        task_track_started=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
    )
    if crontab is not None:
        celery_app.conf.beat_schedule = {
            "purge-expired-data-nightly": {
                "task": JOB_SPECS["retention_purge"].task_name,
                "schedule": crontab(hour=2, minute=0),
            }
        }

    def _retry_or_fail(self, job_id: str, exc: Exception):
        async def _update():
            async with async_session_factory() as session:
                job = await job_state_service.get_job(session, job_id)
                if job is None:
                    return None
                countdown = job_state_service.retry_countdown(job, getattr(self.request, "retries", 0))
                metadata = {
                    "last_exception_type": type(exc).__name__,
                    "worker_task_id": getattr(self.request, "id", None),
                }
                if getattr(self.request, "retries", 0) < job.max_retries:
                    await job_state_service.mark_retry_scheduled(
                        session,
                        job.id,
                        error_message=str(exc),
                        countdown_seconds=countdown,
                        metadata=metadata,
                    )
                    await session.commit()
                    return {"retry": True, "countdown": countdown, "max_retries": job.max_retries}

                await job_state_service.mark_dead_lettered(
                    session,
                    job.id,
                    error_message=str(exc),
                    metadata={**metadata, "dead_lettered": True},
                )
                await session.commit()
                return {"retry": False}

        retry_state = asyncio.run(_update())
        if retry_state and retry_state.get("retry"):
            raise self.retry(
                exc=exc,
                countdown=retry_state["countdown"],
                max_retries=retry_state["max_retries"],
            )
        raise exc

    @celery_app.task(
        bind=True,
        name=JOB_SPECS["document_processing"].task_name,
        soft_time_limit=settings.document_processing_timeout_seconds,
    )
    def process_document_task(self, document_id: str, job_id: str | None = None):
        try:
            if job_id is None:
                raise ValueError("job_id is required for document processing tasks")
            return _execute_job_sync(
                job_id=job_id,
                default_job_type="document_processing",
                runner=_run_document_processing,
                runner_args=(document_id,),
                worker_task_id=getattr(self.request, "id", None),
            )
        except SoftTimeLimitExceeded as exc:
            _retry_or_fail(self, job_id or document_id, TimeoutError("Document processing timed out"))  # pragma: no cover
            raise exc
        except Exception as exc:
            _retry_or_fail(self, job_id or document_id, exc)

    @celery_app.task(
        bind=True,
        name=JOB_SPECS["evaluation_run"].task_name,
        soft_time_limit=settings.evaluation_timeout_seconds,
    )
    def run_evaluation_task(self, job_id: str):
        try:
            return _execute_job_sync(
                job_id=job_id,
                default_job_type="evaluation_run",
                runner=_run_evaluation,
                runner_args=(job_id,),
                worker_task_id=getattr(self.request, "id", None),
            )
        except SoftTimeLimitExceeded as exc:
            _retry_or_fail(self, job_id, TimeoutError("Evaluation run timed out"))  # pragma: no cover
            raise exc
        except Exception as exc:
            _retry_or_fail(self, job_id, exc)

    @celery_app.task(
        bind=True,
        name=JOB_SPECS["image_analysis"].task_name,
        soft_time_limit=settings.image_analysis_timeout_seconds,
    )
    def process_image_analysis_task(self, image_id: str, additional_context: str = "", job_id: str | None = None):
        try:
            if job_id is None:
                raise ValueError("job_id is required for image analysis tasks")
            return _execute_job_sync(
                job_id=job_id,
                default_job_type="image_analysis",
                runner=_run_image_analysis,
                runner_args=(image_id, additional_context),
                worker_task_id=getattr(self.request, "id", None),
            )
        except SoftTimeLimitExceeded as exc:
            _retry_or_fail(self, job_id or image_id, TimeoutError("Image analysis timed out"))  # pragma: no cover
            raise exc
        except Exception as exc:
            _retry_or_fail(self, job_id or image_id, exc)

    @celery_app.task(
        bind=True,
        name=JOB_SPECS["audio_transcription"].task_name,
        soft_time_limit=settings.audio_transcription_timeout_seconds,
    )
    def process_audio_transcription_task(self, transcript_id: str, job_id: str | None = None):
        try:
            if job_id is None:
                raise ValueError("job_id is required for audio transcription tasks")
            return _execute_job_sync(
                job_id=job_id,
                default_job_type="audio_transcription",
                runner=_run_audio_transcription,
                runner_args=(transcript_id,),
                worker_task_id=getattr(self.request, "id", None),
            )
        except SoftTimeLimitExceeded as exc:
            _retry_or_fail(self, job_id or transcript_id, TimeoutError("Audio transcription timed out"))  # pragma: no cover
            raise exc
        except Exception as exc:
            _retry_or_fail(self, job_id or transcript_id, exc)

    @celery_app.task(
        bind=True,
        name=JOB_SPECS["retention_purge"].task_name,
        soft_time_limit=settings.evaluation_timeout_seconds,
    )
    def purge_expired_data_task(self, job_id: str | None = None):
        try:
            effective_job_id = job_id or "retention-purge"
            return _execute_job_sync(
                job_id=effective_job_id,
                default_job_type="retention_purge",
                runner=_run_retention,
                runner_args=(),
                worker_task_id=getattr(self.request, "id", None),
            )
        except Exception as exc:
            if job_id:
                _retry_or_fail(self, job_id, exc)
            raise

    @celery_app.task(
        bind=True,
        name=JOB_SPECS["fine_tune_training"].task_name,
        soft_time_limit=settings.evaluation_timeout_seconds,
    )
    def fine_tune_training_task(self, job_id: str):
        try:
            return _execute_job_sync(
                job_id=job_id,
                default_job_type="fine_tune_training",
                runner=_run_fine_tune_training,
                runner_args=(job_id,),
                worker_task_id=getattr(self.request, "id", None),
            )
        except SoftTimeLimitExceeded as exc:
            _retry_or_fail(self, job_id, TimeoutError("Fine-tune training timed out"))  # pragma: no cover
            raise exc
        except Exception as exc:
            _retry_or_fail(self, job_id, exc)
else:  # pragma: no cover - exercised indirectly in local/test envs
    celery_app = None
    process_document_task = None
    run_evaluation_task = None
    process_image_analysis_task = None
    process_audio_transcription_task = None
    purge_expired_data_task = None
    fine_tune_training_task = None


async def _dispatch_task(
    task,
    *,
    default_job_type: str,
    runner: Callable[..., dict],
    runner_args: tuple[Any, ...],
    task_args: tuple[Any, ...],
    task_kwargs: dict[str, Any] | None = None,
    job_id: str | None = None,
):
    task_kwargs = task_kwargs or {}
    use_local_eager = settings.celery_task_always_eager

    if job_id is not None and await _check_skip_duplicate_dispatch(job_id):
        job = await _load_job_state(job_id)
        if job is not None:
            if use_local_eager or Celery is None or celery_app is None:
                transport = "local-deduped"
            else:
                transport = "celery-deduped"
            return {"id": job.worker_task_id or str(job.id), "transport": transport}

    if job_id is not None:
        async with async_session_factory() as session:
            if await job_state_service.is_cancel_requested(session, job_id):
                return {"id": job_id, "transport": "cancelled-before-dispatch"}

    if use_local_eager or Celery is None or celery_app is None:
        if _background_jobs_required():
            raise RuntimeError("Celery/Redis broker unavailable; local fallback is disabled in production.")

        local_task_id = job_id or f"local-{default_job_type}"
        if job_id is not None:
            await _mark_job_dispatched(job_id, worker_task_id=local_task_id, transport="local-eager")
            try:
                result = await _execute_job_async(
                    job_id=job_id,
                    default_job_type=default_job_type,
                    runner=runner,
                    runner_args=runner_args,
                    worker_task_id=local_task_id,
                )
            except Exception as exc:
                await _mark_job_failed(
                    job_id,
                    error_message=str(exc),
                    metadata={"dispatch_transport": "local-eager"},
                )
                raise
            return {"id": local_task_id, "transport": "local-eager", "result": result}

        result = await asyncio.to_thread(runner, *runner_args)
        return {"id": local_task_id, "transport": "local-eager", "result": result}

    async_result = task.apply_async(args=task_args, kwargs=task_kwargs)
    if job_id is not None:
        await _mark_job_dispatched(job_id, worker_task_id=async_result.id, transport="celery")
    return {"id": async_result.id, "transport": "celery"}


async def dispatch_document_processing(document_id: str, job_id: str | None = None):
    """Queue a document processing job and return the backend-specific handle."""
    task_kwargs = {"job_id": job_id} if job_id is not None else {}
    return await _dispatch_task(
        process_document_task,
        default_job_type="document_processing",
        runner=_run_document_processing,
        runner_args=(document_id,),
        task_args=(document_id,),
        task_kwargs=task_kwargs,
        job_id=job_id,
    )


async def dispatch_evaluation_run(job_id: str):
    """Queue an evaluation job and return the backend-specific handle."""
    return await _dispatch_task(
        run_evaluation_task,
        default_job_type="evaluation_run",
        runner=_run_evaluation,
        runner_args=(job_id,),
        task_args=(job_id,),
        job_id=job_id,
    )


async def dispatch_image_analysis(image_id: str, *, additional_context: str = "", job_id: str | None = None):
    """Queue a medical image analysis job and return the backend-specific handle."""
    task_kwargs = {"job_id": job_id} if job_id is not None else {}
    return await _dispatch_task(
        process_image_analysis_task,
        default_job_type="image_analysis",
        runner=_run_image_analysis,
        runner_args=(image_id, additional_context),
        task_args=(image_id, additional_context),
        task_kwargs=task_kwargs,
        job_id=job_id,
    )


async def dispatch_audio_transcription(transcript_id: str, *, job_id: str | None = None):
    """Queue an audio transcription job and return the backend-specific handle."""
    task_kwargs = {"job_id": job_id} if job_id is not None else {}
    return await _dispatch_task(
        process_audio_transcription_task,
        default_job_type="audio_transcription",
        runner=_run_audio_transcription,
        runner_args=(transcript_id,),
        task_args=(transcript_id,),
        task_kwargs=task_kwargs,
        job_id=job_id,
    )


async def dispatch_fine_tune_training(job_id: str):
    """Queue a durable fine-tuning job and return the backend-specific handle."""
    return await _dispatch_task(
        fine_tune_training_task,
        default_job_type="fine_tune_training",
        runner=_run_fine_tune_training,
        runner_args=(job_id,),
        task_args=(job_id,),
        job_id=job_id,
    )


async def dispatch_retention_purge(job_id: str | None = None):
    """Queue a retention cleanup run."""
    task_kwargs = {"job_id": job_id} if job_id is not None else {}
    return await _dispatch_task(
        purge_expired_data_task,
        default_job_type="retention_purge",
        runner=_run_retention,
        runner_args=(),
        task_args=(),
        task_kwargs=task_kwargs,
        job_id=job_id,
    )


def background_jobs_health() -> dict:
    """Best-effort broker/worker readiness state."""
    if settings.celery_task_always_eager:
        return {
            "status": "healthy",
            "transport": "local-eager",
            "required": False,
        }

    if Celery is None or celery_app is None:
        return {
            "status": "unhealthy" if _background_jobs_required() else "disabled",
            "transport": "local",
            "required": _background_jobs_required(),
        }

    try:
        with celery_app.connection_for_read() as connection:
            connection.ensure_connection(max_retries=1)
        return {
            "status": "healthy",
            "transport": "celery",
            "required": _background_jobs_required(),
        }
    except Exception as exc:
        return {
            "status": "unhealthy" if _background_jobs_required() else "degraded",
            "transport": "celery",
            "required": _background_jobs_required(),
            "error": str(exc),
        }
