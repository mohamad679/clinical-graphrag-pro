"""
Safe client error envelopes and structured internal logging.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging_config import redact_for_log
from app.core.observability import get_observability_context, new_request_id

SAFE_MESSAGES = {
    "retrieval_failed": "Unable to complete the request safely.",
    "llm_failed": "Unable to complete the request safely.",
    "graph_failed": "Unable to complete the request safely.",
    "streaming_failed": "Unable to complete the request safely.",
    "websocket_failed": "Unable to complete the WebSocket request safely.",
    "tool_failed": "Unable to complete the tool request safely.",
}


def current_request_id() -> str:
    context = get_observability_context()
    return str(context.get("request_id") or new_request_id())


def safe_error_envelope(error_code: str, *, request_id: str | None = None, message: str | None = None) -> dict[str, str]:
    return {
        "error": error_code,
        "message": message or SAFE_MESSAGES.get(error_code, "Unable to complete the request safely."),
        "request_id": request_id or current_request_id(),
    }


def log_internal_error(
    logger: logging.Logger,
    event: str,
    exc: BaseException,
    *,
    error_code: str,
    request_id: str | None = None,
    **metadata: Any,
) -> None:
    logger.error(
        event,
        extra={
            "event": event,
            "error_code": error_code,
            "request_id": request_id or current_request_id(),
            "error_type": type(exc).__name__,
            "error_message": redact_for_log(str(exc), mode="STAGING_REDACTED"),
            **redact_for_log(metadata, mode="STAGING_REDACTED"),
        },
        exc_info=False,
    )
