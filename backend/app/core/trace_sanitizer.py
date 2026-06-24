"""
Trace privacy helpers for browser-facing and internal metadata.
"""

from __future__ import annotations

from typing import Any

from app.core.logging_config import redact_for_log

RAW_TRACE_KEYS = {
    "query",
    "question",
    "expanded_queries",
    "retrieved_chunks",
    "final_context",
    "context",
    "prompt",
    "raw_prompt",
    "raw_tool_output",
    "tool_output",
    "answer",
    "full_answer",
    "chunk_text",
    "text",
}

RAW_SOURCE_KEYS = {
    "text",
    "chunk_text",
    "raw_text",
    "source_text",
    "source_context",
    "final_context",
    "prompt",
    "tool_output",
}

PUBLIC_MESSAGE_METADATA_KEYS = {
    "mode",
    "attached_document_id",
    "attached_image_id",
    "generated_from_message_ids",
    "clinician_review_required",
    "heuristic_evidence_support_score",
    "confidence_score_deprecated",
    "message_kind",
    "prompt_version",
}


def _safe_count(value: Any) -> int:
    return len(value) if isinstance(value, (list, tuple, dict, set)) else 0


def build_public_trace(trace: dict | None) -> dict:
    source = dict(trace or {})
    retrieved = source.get("retrieved_chunks") or []
    citations = source.get("citations") or []
    guardrails = source.get("guardrails") or {}
    return {
        "trace_level": "public",
        "model_used": source.get("model_used"),
        "latency_ms": source.get("latency_ms"),
        "heuristic_evidence_support_score": source.get("heuristic_evidence_support_score"),
        "score_semantics": "heuristic evidence-support score, not calibrated clinical confidence",
        "confidence_score_deprecated": bool(source.get("confidence_score_deprecated")),
        "prompt_version": source.get("prompt_version"),
        "answer_style_version": source.get("answer_style_version"),
        "retrieved_chunk_count": _safe_count(retrieved),
        "citation_count": _safe_count(citations),
        "citation_ids": [item.get("marker") for item in citations if isinstance(item, dict) and item.get("marker")],
        "document_ids": sorted(
            {
                str(item.get("document_id"))
                for item in citations
                if isinstance(item, dict) and item.get("document_id")
            }
        ),
        "guardrails": redact_for_log(guardrails, mode="PRODUCTION_METADATA_ONLY"),
        "ready_to_stream": bool(source.get("ready_to_stream")),
        "state_transitions": [
            {
                "state": item.get("state"),
                "timestamp": item.get("timestamp"),
            }
            for item in source.get("state_transitions", [])
            if isinstance(item, dict)
        ],
    }


def build_debug_redacted_trace(trace: dict | None) -> dict:
    redacted = redact_for_log(dict(trace or {}), mode="PRODUCTION_METADATA_ONLY")
    for key in RAW_TRACE_KEYS:
        if key in redacted:
            redacted[key] = {"redacted": True, "reason": "debug_redacted_trace"}
    return {
        **redacted,
        "trace_level": "debug_redacted",
    }


def build_internal_audit_trace(trace: dict | None, *, full_enabled: bool = False) -> dict:
    if full_enabled:
        return {**dict(trace or {}), "trace_level": "internal_full"}
    return {
        **build_public_trace(trace),
        "trace_level": "internal_metadata_only",
        "retention_policy": "metadata_only_default",
    }


def sanitize_source_reference(source: dict | None) -> dict:
    """Return a browser-safe source reference without raw chunk or prompt text."""
    cleaned: dict[str, Any] = {}
    for key, value in dict(source or {}).items():
        if key in RAW_SOURCE_KEYS:
            continue
        if isinstance(value, str) and key.lower().endswith("text"):
            continue
        cleaned[key] = value
    return cleaned


def sanitize_source_references(sources: list | tuple | dict | None) -> list | dict | None:
    """Sanitize public source payloads while preserving stable citation/chunk identifiers."""
    if sources is None:
        return None
    if isinstance(sources, dict):
        return sanitize_source_reference(sources)
    if isinstance(sources, (list, tuple)):
        return [sanitize_source_reference(source) if isinstance(source, dict) else source for source in sources]
    return None


def build_public_message_metadata(
    metadata: dict | None,
    *,
    trace_level: str = "public",
    debug_trace_authorized: bool = False,
) -> dict:
    """Build metadata safe for browser history/message responses.

    Internal audit traces may contain richer operational metadata when explicitly
    enabled. Public history never returns internal_full traces, raw prompts,
    retrieved chunk text, final context, tool output, or internal exception text.
    """
    source = dict(metadata or {})
    public = {key: source[key] for key in PUBLIC_MESSAGE_METADATA_KEYS if key in source}
    trace = source.get("trace")
    if isinstance(trace, dict):
        if trace_level == "debug_redacted" and debug_trace_authorized:
            public["trace"] = build_debug_redacted_trace(trace)
        else:
            public["trace"] = build_public_trace(trace)
    return public
