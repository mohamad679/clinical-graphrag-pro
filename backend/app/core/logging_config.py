"""
Structured JSON logging with request tracing.
"""

from __future__ import annotations

import json
import logging
import hashlib
import re
import sys
import time
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.observability import (
    bind_observability_context,
    export_trace_context,
    get_observability_context,
    new_request_id,
    new_trace_id,
)


CONTEXT_FIELDS = {
    "request_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "component",
    "operation",
    "event",
    "status",
    "user_id",
    "session_id",
    "endpoint",
    "job_id",
    "task_type",
    "document_id",
    "image_id",
    "transcript_id",
    "workflow_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "client_ip",
    "error_type",
    "error_message",
}

SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "secret",
    "secret_key",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "jwt",
}

RAW_TEXT_KEYS = {
    "query",
    "question",
    "message",
    "prompt",
    "system_prompt",
    "context",
    "final_context",
    "chunk_text",
    "text",
    "answer",
    "full_answer",
    "content",
    "raw_text",
    "normalized_text",
    "tool_output",
    "output",
    "result",
    "trace",
    "sources",
    "citations",
}

PATH_KEYS = {
    "path",
    "file_path",
    "thumbnail_path",
    "local_path",
    "filename",
    "original_filename",
    "object_key",
}

OBSERVABILITY_LOCAL_SYNTHETIC_DEBUG = "LOCAL_SYNTHETIC_DEBUG"
OBSERVABILITY_STAGING_REDACTED = "STAGING_REDACTED"
OBSERVABILITY_PRODUCTION_METADATA_ONLY = "PRODUCTION_METADATA_ONLY"

API_KEY_PATTERNS = [
    # Google API Key / Gemini API Key
    r"\bAIzaSy[a-zA-Z0-9_-]{33}\b",
    # Bearer tokens / JWTs
    r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{15,}",
    # General auth keys / secret query string keys in LLM logs (like API keys)
    r"(?i)(key|token|auth|password|secret|pass|credential|signature)=(?:[a-zA-Z0-9_\-\.]{10,})",
    # Groq API Keys (starts with gsk_)
    r"\bgsk_[a-zA-Z0-9]{48}\b",
    # Database URLs with credentials
    r"(?i)\b(?:postgresql|postgres|mysql|mariadb|redis|rediss|mongodb)://[^\s]+",
    # Local absolute paths that may contain patient or developer identifiers
    r"(?:/Users|/home|/private|/var|/tmp)/[^\s,;:]+",
]


def redact_secrets(text: str) -> str:
    """Regex-based credentials redaction in strings and logs."""
    if not isinstance(text, str):
        return text
    redacted = text
    for pattern in API_KEY_PATTERNS:
        if "=" in pattern:
            def replace_param(match):
                full = match.group(0)
                prefix = full.split("=")[0]
                return f"{prefix}=[REDACTED]"
            redacted = re.compile(pattern).sub(replace_param, redacted)
        else:
            redacted = re.compile(pattern).sub("[REDACTED]", redacted)
    return redacted


def _active_observability_mode() -> str:
    try:
        from app.core.config import get_settings

        return get_settings().observability_mode
    except Exception:
        return OBSERVABILITY_LOCAL_SYNTHETIC_DEBUG


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _redacted_metadata(value: Any, reason: str) -> dict[str, Any]:
    if isinstance(value, str):
        return {
            "redacted": True,
            "reason": reason,
            "length": len(value),
            "sha256_prefix": _hash_value(value),
        }
    if isinstance(value, (list, tuple, set)):
        return {"redacted": True, "reason": reason, "item_count": len(value)}
    if isinstance(value, dict):
        return {"redacted": True, "reason": reason, "key_count": len(value)}
    return {"redacted": True, "reason": reason, "type": type(value).__name__}


def _metadata_only_key(key_text: str) -> bool:
    return any(marker == key_text or marker in key_text for marker in RAW_TEXT_KEYS)


def _path_key(key_text: str) -> bool:
    return any(marker == key_text or marker in key_text for marker in PATH_KEYS)


def redact_for_log(value: Any, *, mode: str | None = None) -> Any:
    """Recursively redact common credential fields before JSON serialization."""
    active_mode = (mode or _active_observability_mode()).strip().upper()
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in SENSITIVE_KEYS):
                redacted[str(key)] = "[REDACTED]"
            elif active_mode == OBSERVABILITY_PRODUCTION_METADATA_ONLY and _metadata_only_key(key_text):
                redacted[str(key)] = _redacted_metadata(item, "metadata_only_observability")
            elif active_mode in {OBSERVABILITY_STAGING_REDACTED, OBSERVABILITY_PRODUCTION_METADATA_ONLY} and _path_key(key_text):
                redacted[str(key)] = _redacted_metadata(str(item), "path_redacted")
            else:
                redacted[str(key)] = redact_for_log(item, mode=active_mode)
        return redacted
    if isinstance(value, list):
        return [redact_for_log(item, mode=active_mode) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_log(item, mode=active_mode) for item in value)
    if isinstance(value, BaseException):
        return {
            "error_type": type(value).__name__,
            "error_message": redact_secrets(str(value)),
        }
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def _request_related_ids(request: Request) -> dict[str, Any]:
    path_params = dict(request.path_params or {})
    state = request.state
    return {
        "job_id": getattr(state, "job_id", None) or path_params.get("job_id"),
        "task_type": getattr(state, "task_type", None) or path_params.get("task_type"),
        "document_id": getattr(state, "document_id", None) or path_params.get("document_id"),
        "image_id": getattr(state, "image_id", None) or path_params.get("image_id"),
        "session_id": getattr(state, "session_id", None) or path_params.get("session_id"),
    }


def _extract_token_claims(request: Request) -> dict[str, Any] | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        from app.core.auth import auth_service

        return auth_service.verify_token(token)
    except Exception:
        return None


def _normalize_path(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if route_path:
        return str(route_path)
    return request.url.path


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        active_mode = _active_observability_mode()
        raw_message = record.getMessage()
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": (
                _redacted_metadata(raw_message, "metadata_only_observability")
                if active_mode == OBSERVABILITY_PRODUCTION_METADATA_ONLY
                else redact_for_log(raw_message, mode=active_mode)
            ),
        }

        # Merge bound observability context first, then explicit record extras.
        context = get_observability_context()
        log_entry.update(redact_for_log({key: value for key, value in context.items() if value is not None}))
        for key in CONTEXT_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = redact_for_log(value)

        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "asctime",
            }:
                continue
            if key in CONTEXT_FIELDS or key not in log_entry:
                log_entry[key] = redact_for_log(value)

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = redact_for_log(self.formatException(record.exc_info))

        return json.dumps(log_entry)


class RequestMetrics:
    """Track request metrics for the admin dashboard."""

    def __init__(self):
        self.total_requests: int = 0
        self.total_errors: int = 0
        self.status_counts: dict[int, int] = {}
        self.latencies: list[float] = []  # Last 1000 latencies in ms
        self.endpoint_counts: dict[str, int] = {}

    def record(self, path: str, status_code: int, duration_ms: float):
        self.total_requests += 1
        if status_code >= 400:
            self.total_errors += 1
        self.status_counts[status_code] = self.status_counts.get(status_code, 0) + 1
        self.endpoint_counts[path] = self.endpoint_counts.get(path, 0) + 1
        self.latencies.append(duration_ms)
        if len(self.latencies) > 1000:
            self.latencies = self.latencies[-1000:]

    def get_summary(self) -> dict:
        avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0
        p95_latency = sorted(self.latencies)[int(len(self.latencies) * 0.95)] if len(self.latencies) > 10 else avg_latency
        error_rate = (self.total_errors / self.total_requests * 100) if self.total_requests > 0 else 0

        return {
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate_pct": round(error_rate, 2),
            "avg_latency_ms": round(avg_latency, 1),
            "p95_latency_ms": round(p95_latency, 1),
            "status_counts": dict(sorted(self.status_counts.items())),
            "top_endpoints": dict(
                sorted(self.endpoint_counts.items(), key=lambda x: -x[1])[:10]
            ),
        }


# Module-level singleton
request_metrics = RequestMetrics()


def setup_logging(json_output: bool = False, level: str = "INFO"):
    """Configure application logging."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
        )

    root.addHandler(handler)

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with timing and capture metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or new_request_id()
        trace_id = request.headers.get("x-trace-id") or new_trace_id()
        client_ip = request.client.host if request.client else "unknown"
        endpoint = _normalize_path(request)
        claims = _extract_token_claims(request) or {}
        start = time.monotonic()

        # Attach request_id to request state for downstream use
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request.state.endpoint = endpoint
        request.state.user_id = claims.get("sub")
        request.state.session_id = claims.get("sid")

        with bind_observability_context(
            request_id=request_id,
            trace_id=trace_id,
            endpoint=endpoint,
            method=request.method,
            path=request.url.path,
            user_id=claims.get("sub"),
            session_id=claims.get("sid"),
        ):
            try:
                response = await call_next(request)
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
                request_metrics.record(endpoint, 500, duration_ms)
                related_ids = _request_related_ids(request)
                logging.getLogger("http").error(
                    "request.failed",
                    extra={
                        **export_trace_context(),
                        **related_ids,
                        "event": "request.failed",
                        "status_code": 500,
                        "duration_ms": round(duration_ms, 2),
                        "client_ip": client_ip,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                raise

            duration_ms = (time.monotonic() - start) * 1000
            request_metrics.record(endpoint, response.status_code, duration_ms)
            related_ids = _request_related_ids(request)

            if not request.url.path.endswith("/health"):
                logging.getLogger("http").info(
                    "request.completed",
                    extra={
                        **export_trace_context(),
                        **related_ids,
                        "event": "request.completed",
                        "status_code": response.status_code,
                        "duration_ms": round(duration_ms, 2),
                        "client_ip": client_ip,
                    },
                )

            response.headers["X-Request-ID"] = request_id
            response.headers["X-Trace-ID"] = trace_id
            return response
