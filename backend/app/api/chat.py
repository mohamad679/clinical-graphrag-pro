"""
Chat API endpoints — SSE streaming, session persistence, and WebSocket support.
"""

import json
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.redis import redis_service
from app.models.chat import ChatSession, ChatMessage
from app.schemas.chat import (
    ChatRequest,
    ChatSessionResponse,
    ChatMessageResponse,
)
from app.services.rag import rag_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


# ── SSE Streaming Endpoint ───────────────────────────────

@router.post("")
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Stream a RAG-powered response via Server-Sent Events.
    Persists the conversation to PostgreSQL.

    Events:
      - type: "reasoning"  → chain-of-thought step
      - type: "source"     → retrieved source references
      - type: "token"      → generated text token
      - type: "done"       → stream complete
      - type: "error"      → error occurred
    """

    # Resolve or create session
    if request.session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == request.session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = ChatSession(title=request.message[:80])
        db.add(session)
        await db.flush()  # get the ID

    session_id = session.id

    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=request.message,
    )
    db.add(user_msg)
    await db.flush()

    # Load chat history for context
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    history_rows = history_result.scalars().all()
    chat_history = [
        {"role": m.role, "content": m.content}
        for m in history_rows[-10:]  # last 10 messages
        if m.role in ("user", "assistant")
    ]

    # We need to commit the user message before streaming
    await db.commit()

    async def event_generator():
        collected_tokens = []
        collected_sources = None

        async for chunk in rag_service.query_stream(
            question=request.message,
            top_k=5,
            chat_history=chat_history,
        ):
            if chunk.get("type") == "token":
                collected_tokens.append(chunk.get("content", ""))
            elif chunk.get("type") == "source":
                collected_sources = chunk.get("sources")

            event_data = json.dumps(chunk)
            yield f"data: {event_data}\n\n"

        # Save assistant response to DB
        try:
            async with (await _get_session()) as save_db:
                assistant_content = "".join(collected_tokens)
                assistant_msg = ChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=assistant_content,
                    sources=collected_sources,
                    token_count=len(collected_tokens),
                )
                save_db.add(assistant_msg)
                await save_db.commit()

                # Cache in Redis
                cache_key = f"chat:last_response:{session_id}"
                await redis_service.set(cache_key, {
                    "answer": assistant_content,
                    "sources": collected_sources,
                }, ttl=1800)

        except Exception as e:
            logger.error(f"Failed to save assistant message: {e}")

        # Final event
        final = json.dumps({
            "type": "done",
            "session_id": str(session_id),
        })
        yield f"data: {final}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Non-streaming sync endpoint ──────────────────────────

@router.post("/sync")
async def chat_sync(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Non-streaming chat endpoint for testing."""
    result = await rag_service.query(
        question=request.message,
        top_k=5,
    )
    return result


# ── Session Management ───────────────────────────────────

@router.get("/sessions")
async def list_sessions(db: AsyncSession = Depends(get_db)):
    """List all chat sessions."""
    result = await db.execute(
        select(ChatSession).order_by(ChatSession.updated_at.desc())
    )
    sessions = result.scalars().all()
    return [
        ChatSessionResponse(
            id=s.id,
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
            message_count=len(s.messages),
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a session with all messages."""
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
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
            ChatMessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                sources=m.sources,
                reasoning_steps=m.reasoning_steps,
                created_at=m.created_at,
            )
            for m in session.messages
        ],
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a chat session and all its messages."""
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(session)
    return {"message": "Session deleted"}


# ── WebSocket for real-time chat ─────────────────────────

@router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time bidirectional chat.
    Clients send JSON: {"message": "..."}
    Server sends JSON events matching the SSE format.
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: session={session_id}")

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")

            if not message:
                await websocket.send_json({"type": "error", "content": "Empty message"})
                continue

            # Stream RAG response over WebSocket
            async for chunk in rag_service.query_stream(
                question=message,
                top_k=5,
            ):
                await websocket.send_json(chunk)

            await websocket.send_json({
                "type": "done",
                "session_id": session_id,
            })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session={session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


# ── Helper ───────────────────────────────────────────────

async def _get_session():
    """Get a new async DB session (for use outside FastAPI dependency injection)."""
    from app.core.database import async_session_factory
    return async_session_factory()
