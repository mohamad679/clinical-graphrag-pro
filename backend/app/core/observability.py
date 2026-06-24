"""
Shared observability context and lightweight distributed tracing helpers.
"""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("trace")

_OBSERVABILITY_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "observability_context",
    default={},
)


def _clean_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def get_observability_context() -> dict[str, Any]:
    return dict(_OBSERVABILITY_CONTEXT.get())


def current_trace_id() -> str:
    return str(get_observability_context().get("trace_id") or new_trace_id())


def export_trace_context() -> dict[str, Any]:
    context = get_observability_context()
    keys = (
        "request_id",
        "trace_id",
        "user_id",
        "session_id",
        "endpoint",
        "method",
        "job_id",
        "task_type",
        "document_id",
        "image_id",
        "transcript_id",
        "workflow_id",
    )
    return {key: context[key] for key in keys if context.get(key) is not None}


@contextmanager
def bind_observability_context(**fields: Any) -> Iterator[dict[str, Any]]:
    current = get_observability_context()
    updated = {**current, **_clean_fields(fields)}
    token = _OBSERVABILITY_CONTEXT.set(updated)
    try:
        yield updated
    finally:
        _OBSERVABILITY_CONTEXT.reset(token)


def update_observability_context(**fields: Any) -> dict[str, Any]:
    current = get_observability_context()
    updated = {**current, **_clean_fields(fields)}
    _OBSERVABILITY_CONTEXT.set(updated)
    return updated


@contextmanager
def trace_operation(
    operation: str,
    *,
    component: str,
    logger_: logging.Logger | None = None,
    emit_start: bool = False,
    **fields: Any,
) -> Iterator[dict[str, Any]]:
    active_logger = logger_ or logger
    parent_context = get_observability_context()
    trace_id = str(parent_context.get("trace_id") or new_trace_id())
    span_id = new_span_id()
    parent_span_id = parent_context.get("span_id")
    span_fields = {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "component": component,
        "operation": operation,
        **_clean_fields(fields),
    }
    start = time.perf_counter()
    with bind_observability_context(**span_fields):
        if emit_start:
            active_logger.info(
                "span.started",
                extra={**span_fields, "event": "span.started"},
            )
        try:
            yield get_observability_context()
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            active_logger.error(
                "span.failed",
                extra={
                    **span_fields,
                    "event": "span.failed",
                    "status": "error",
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            active_logger.info(
                "span.completed",
                extra={
                    **span_fields,
                    "event": "span.completed",
                    "status": "ok",
                    "duration_ms": duration_ms,
                },
            )
