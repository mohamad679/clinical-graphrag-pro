"""
Chat API endpoints — unified sync/stream orchestration, session persistence, and WebSocket support.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.auth import User, auth_service, require_authenticated_user
from app.core.database import async_session_factory, get_db
from app.core.error_envelope import log_internal_error, safe_error_envelope
from app.core.metrics import mark_chat_request
from app.core.rate_limiter import rate_limiter
from app.core.trace_sanitizer import build_public_message_metadata, sanitize_source_references
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User as DBUser
from app.schemas.chat import (
    ChatFeedback,
    ChatMessageResponse,
    ChatRequest,
    ChatSessionResponse,
)
from app.services.chat_orchestrator import chat_orchestrator
from app.services.websocket_ticket import websocket_ticket_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


def _websocket_ticket(websocket: WebSocket) -> str | None:
    query_ticket = websocket.query_params.get("ticket")
    return query_ticket.strip() if query_ticket else None


def _debug_trace_authorized(user: User, *, trace_level: str) -> bool:
    if trace_level != "debug_redacted":
        return False
    settings = get_settings()
    return user.role == "admin" and settings.app_env != "production" and settings.debug


def _message_response(
    message: ChatMessage,
    *,
    trace_level: str = "public",
    debug_trace_authorized: bool = False,
) -> ChatMessageResponse:
    metadata = build_public_message_metadata(
        message.metadata_,
        trace_level=trace_level,
        debug_trace_authorized=debug_trace_authorized,
    )
    return ChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        sources=sanitize_source_references(message.sources),
        reasoning_steps=message.reasoning_steps,
        confidence_score=message.confidence_score,
        heuristic_evidence_support_score=metadata.get("heuristic_evidence_support_score"),
        metadata=metadata,
        created_at=message.created_at,
    )


@router.post("")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    """Stream a grounded response via Server-Sent Events."""
    mark_chat_request()

    async def event_generator():
        try:
            async for event in chat_orchestrator.stream(db, request, user):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            request_id = getattr(request, "request_id", None)
            log_internal_error(logger, "chat.stream_failed", exc, error_code="streaming_failed", request_id=request_id)
            yield f"data: {json.dumps({'type': 'error', **safe_error_envelope('streaming_failed', request_id=request_id)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sync")
async def chat_sync(
    request: ChatRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
    trace_level: str = "public",
):
    """Non-streaming chat endpoint with the same orchestration path as SSE chat."""
    mark_chat_request()
    if trace_level not in {"public", "debug_redacted"}:
        raise HTTPException(status_code=400, detail="Unsupported trace level")
    debug_allowed = _debug_trace_authorized(user, trace_level=trace_level)
    if trace_level == "debug_redacted" and not debug_allowed:
        raise HTTPException(status_code=403, detail="Debug trace is not available")
    try:
        payload = await chat_orchestrator.execute_sync(
            db,
            request,
            user,
            trace_level=trace_level,
            debug_trace_authorized=debug_allowed,
        )
    except HTTPException:
        raise
    except Exception as exc:
        request_id = getattr(http_request.state, "request_id", None)
        log_internal_error(logger, "chat.sync_failed", exc, error_code="retrieval_failed", request_id=request_id)
        return safe_error_envelope("retrieval_failed", request_id=request_id)
    http_request.state.session_id = payload.get("session_id")
    return payload


@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    """List all chat sessions."""
    try:
        query = select(ChatSession).options(selectinload(ChatSession.messages)).order_by(ChatSession.updated_at.desc())
        if user.role != "admin":
            query = query.where(ChatSession.user_id == user.id)
        result = await db.execute(query)
        sessions = result.scalars().all()
        return [
            ChatSessionResponse(
                id=session.id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                message_count=len(session.messages or []),
            )
            for session in sessions
        ]
    except Exception as exc:
        settings = get_settings()
        log_internal_error(logger, "chat.sessions_list_failed", exc, error_code="chat_sessions_failed")
        if settings.enable_demo_auth and settings.app_env != "production":
            return []
        raise


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
    trace_level: str = "public",
):
    """Get a session with all messages."""
    if trace_level not in {"public", "debug_redacted"}:
        raise HTTPException(status_code=400, detail="Unsupported trace level")
    debug_allowed = _debug_trace_authorized(user, trace_level=trace_level)
    if trace_level == "debug_redacted" and not debug_allowed:
        raise HTTPException(status_code=403, detail="Debug trace is not available")

    result = await db.execute(
        select(ChatSession).options(selectinload(ChatSession.messages)).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if user.role != "admin" and session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session": ChatSessionResponse(
            id=session.id,
            title=session.title,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=len(session.messages),
        ),
        "messages": [
            _message_response(message, trace_level=trace_level, debug_trace_authorized=debug_allowed)
            for message in session.messages
        ],
    }


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    """Delete a chat session and all its messages."""
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if user.role != "admin" and session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(session)
    return {"message": "Session deleted"}


@router.post("/messages/{message_id}/feedback")
async def submit_feedback(
    message_id: uuid.UUID,
    feedback: ChatFeedback,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    """Submit a 1-5 star rating and optional comment for an AI message."""
    result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    from app.models.user_feedback import UserFeedback

    existing = await db.execute(select(UserFeedback).where(UserFeedback.message_id == str(message_id)))
    existing_feedback = existing.scalar_one_or_none()

    if existing_feedback:
        existing_feedback.rating = feedback.rating
        existing_feedback.comment = feedback.comment
        existing_feedback.user_id = user.id
    else:
        db.add(
            UserFeedback(
                user_id=user.id,
                message_id=str(message_id),
                session_id=str(message.session_id),
                rating=feedback.rating,
                comment=feedback.comment,
            )
        )

    await db.commit()
    return {"success": True, "message": "Feedback recorded."}


@router.post("/sessions/{session_id}/generate-note")
async def generate_clinical_note(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    """Generate a traceable SOAP note from persisted chat history."""
    return await chat_orchestrator.generate_note(db, session_id, user)


@router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for authenticated safe chat streaming.
    """
    ticket = _websocket_ticket(websocket)
    if not ticket:
        await websocket.close(code=1008, reason="Authentication required")
        return

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        await websocket.close(code=1008, reason="Invalid session")
        return

    async with async_session_factory() as db:
        try:
            ticket_record = await websocket_ticket_service.consume_ticket(
                ticket,
                expected_session_id=str(session_uuid),
            )
            if ticket_record is None:
                await websocket.close(code=1008, reason="Invalid WebSocket ticket")
                return
            result = await db.execute(select(DBUser).where(DBUser.id == ticket_record.user_id))
            db_user = result.scalar_one_or_none()
            if db_user is None or not db_user.is_active:
                await websocket.close(code=1008, reason="Authentication failed")
                return
            user = auth_service._to_user_context(db_user, session_id=ticket_record.session_id)
            if (user.tenant_id or user.id) != ticket_record.tenant_id:
                await websocket.close(code=1008, reason="Authentication failed")
                return
            await db.commit()
            await chat_orchestrator._get_session_or_404(db, session_uuid, user)
        except HTTPException as exc:
            await websocket.close(code=1008, reason=str(exc.detail))
            return
        except Exception:
            logger.exception("WebSocket authentication failed")
            await websocket.close(code=1008, reason="Authentication failed")
            return

        await websocket.accept()
        websocket.state.user_id = user.id
        websocket.state.user = user
        logger.info("WebSocket connected: session=%s", session_id)

        try:
            while True:
                data = await websocket.receive_json()
                message = str(data.get("message", "")).strip()
                if not message:
                    await websocket.send_json({"type": "error", "code": "EMPTY_MESSAGE", "content": "Empty message"})
                    continue

                try:
                    await rate_limiter.check(websocket)
                except HTTPException as exc:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "RATE_LIMITED",
                            "content": str(exc.detail),
                        }
                    )
                    continue

                mark_chat_request()
                request = ChatRequest(message=message, session_id=session_uuid)
                async for event in chat_orchestrator.stream(db, request, user):
                    await websocket.send_json(event)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected: session=%s", session_id)
        except Exception as exc:
            log_internal_error(logger, "chat.websocket_failed", exc, error_code="websocket_failed")
            try:
                await websocket.send_json(
                    {"type": "error", "code": "WEBSOCKET_ERROR", **safe_error_envelope("websocket_failed")}
                )
            except Exception:
                pass
