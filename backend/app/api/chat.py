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
from app.models.medical_image import MedicalImage
from sqlalchemy.orm import selectinload
from app.schemas.chat import (
    ChatRequest,
    ChatSessionResponse,
    ChatMessageResponse,
    ChatFeedback,
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

        if request.attached_image_id:
            # ── Multi-modal Vision Chat ─────────────────────
            img_result = await db.execute(
                select(MedicalImage)
                .options(selectinload(MedicalImage.annotations))
                .where(MedicalImage.id == request.attached_image_id)
            )
            image = img_result.scalar_one_or_none()
            
            if not image:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Attached image not found'})}\n\n"
                return
                
            yield f"data: {json.dumps({'type': 'reasoning', 'step': 1, 'title': 'Image Analysis', 'description': f'Loading vision context for {image.original_filename}', 'status': 'running'})}\n\n"
            
            # --- Dynamic Vision Analysis ---
            if not image.analysis_result:
                yield f"data: {json.dumps({'type': 'reasoning', 'step': 1.5, 'title': 'Vision Processing', 'description': 'Triggering Vision LLM to extract biomedical features from image...', 'status': 'running'})}\n\n"
                try:
                    from app.services.vision import vision_service
                    from pathlib import Path
                    from datetime import datetime, timezone
                    
                    image_path = Path(image.file_path)
                    image_data = image_path.read_bytes()
                    
                    analysis = await vision_service.analyze_image(
                        image_data, image.mime_type, ""
                    )
                    
                    # Update the DB record
                    image.analysis_result = analysis
                    image.analysis_status = "completed" if "error" not in analysis else "failed"
                    image.analyzed_at = datetime.now(timezone.utc)
                    image.modality = analysis.get("modality_detected")
                    image.body_part = analysis.get("body_part_detected")
                    
                    await db.commit()
                    await db.refresh(image)
                    
                    yield f"data: {json.dumps({'type': 'reasoning', 'step': 1.5, 'title': 'Vision Processing', 'description': 'Vision Extraction Complete.', 'status': 'done'})}\n\n"
                except Exception as e:
                    logger.error(f"Dynamic image analysis failed: {e}")
            # -------------------------------
            
            yield f"data: {json.dumps({'type': 'reasoning', 'step': 1, 'title': 'Image Analysis', 'description': 'Context Loaded', 'status': 'done'})}\n\n"

            # Format image context
            analysis = image.analysis_result or {}
            img_context = f"Image Name: {image.original_filename}\n"
            
            if "error" in analysis:
                err_msg = analysis.get("error", "Unknown vision error")
                img_context += f"WARNING TO AI: The Vision Extraction API completely failed. Here is the exact error: {err_msg}\n"
                img_context += f"ACTION REQUIRED: Respond to the user gracefully, apologizing that you cannot see the image because the Vision API quota is exhausted or failed. Do not say 'the context says None'. Explain the actual technical limitation.\n"
            else:
                img_context += f"Detected Modality: {image.modality}\n"
                img_context += f"Body Part: {image.body_part}\n"
                img_context += f"Summary: {analysis.get('summary', 'No summary available')}\n"
                
                if analysis.get('findings'):
                    img_context += "\nKey Findings:\n" + "\n".join(f"- {f.get('description', str(f)) if isinstance(f, dict) else f}" for f in analysis['findings'])
                if analysis.get('recommendations'):
                    img_context += "\nRecommendations:\n" + "\n".join(f"- {r}" for r in analysis['recommendations'])
                if analysis.get('differential_diagnosis'):
                    img_context += "\nDifferential Diagnosis:\n" + "\n".join(f"- {d.get('condition', str(d)) if isinstance(d, dict) else d}" for d in analysis['differential_diagnosis'])
                    
            # Add annotations
            if image.annotations:
                img_context += "\n\nSpecific User or AI Annotations identified in the image:\n"
                for ann in image.annotations:
                    img_context += f"- {ann.label} ({ann.annotation_type})"
                    if ann.notes:
                        img_context += f": {ann.notes}"
                    img_context += "\n"

            # Route directly to LLM Service with this image context
            from app.services.llm import llm_service
            yield f"data: {json.dumps({'type': 'reasoning', 'step': 2, 'title': 'Generating answer', 'description': 'Streaming response based on medical image analysis...', 'status': 'running'})}\n\n"
            
            collected_sources = [{"document_id": str(image.id), "document_name": image.original_filename, "chunk_index": 0, "text": "Image Analysis Data", "relevance_score": 1.0}]
            yield f"data: {json.dumps({'type': 'source', 'sources': collected_sources})}\n\n"
            
            try:
                async for token in llm_service.generate_stream(
                    user_message=request.message,
                    context=img_context,
                    chat_history=chat_history,
                ):
                    collected_tokens.append(token)
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            except Exception as e:
                logger.error(f"Image chat generation failed: {e}")
                yield f"data: {json.dumps({'type': 'error', 'content': f'Generation failed: {str(e)}'})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'reasoning', 'step': 2, 'title': 'Generating answer', 'description': 'Response complete.', 'status': 'done'})}\n\n"

        elif request.attached_document_id:
            # ── Multi-modal Document Chat ─────────────────────
            from app.services.vector_store import vector_store_service
            yield f"data: {json.dumps({'type': 'reasoning', 'step': 1, 'title': 'Document Analysis', 'description': 'Loading document content for focused analysis...', 'status': 'done'})}\n\n"
            
            all_chunks = vector_store_service.get_all_chunks()
            doc_chunks = [c for c in all_chunks if str(c.get("document_id")) == str(request.attached_document_id)]
            
            if not doc_chunks:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Attached document not found or has no content'})}\n\n"
                return
                
            doc_name = doc_chunks[0].get("document_name", "Unknown Document")
            
            doc_context = f"Document Name: {doc_name}\n\nContent:\n"
            for i, c in enumerate(doc_chunks[:10]):  # Limit to 10 chunks (~5k tokens) to prevent 413 Payload Too Large
                doc_context += f"--- Part {i+1} ---\n{c.get('chunk_text', '')}\n"
                
            collected_sources = [{"document_id": str(request.attached_document_id), "document_name": doc_name, "chunk_index": i, "text": c.get("chunk_text", "")[:200], "relevance_score": 1.0} for i, c in enumerate(doc_chunks[:5])]
            
            yield f"data: {json.dumps({'type': 'reasoning', 'step': 2, 'title': 'Generating answer', 'description': 'Streaming response based only on the attached document...', 'status': 'running'})}\n\n"
            yield f"data: {json.dumps({'type': 'source', 'sources': collected_sources})}\n\n"
            
            from app.services.llm import llm_service
            try:
                async for token in llm_service.generate_stream(
                    user_message=request.message,
                    context=doc_context,
                    chat_history=chat_history,
                ):
                    collected_tokens.append(token)
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            except Exception as e:
                logger.error(f"Document chat generation failed: {e}")
                yield f"data: {json.dumps({'type': 'error', 'content': f'Generation failed: {str(e)}'})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'reasoning', 'step': 2, 'title': 'Generating answer', 'description': 'Response complete.', 'status': 'done'})}\n\n"

        else:
            # ── Standard RAG Pipeline ───────────────────────
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


@router.post("/messages/{message_id}/feedback")
async def submit_feedback(
    message_id: uuid.UUID, 
    feedback: ChatFeedback, 
    db: AsyncSession = Depends(get_db)
):
    """Submit a rating (+1 / -1) and optional comment for an AI message."""
    # Verify message exists
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
        
    # Import locally to avoid circular dependencies if any
    from app.models.user_feedback import UserFeedback
    
    # Check if feedback already exists
    existing = await db.execute(
        select(UserFeedback).where(UserFeedback.message_id == str(message_id))
    )
    existing_fb = existing.scalar_one_or_none()
    
    if existing_fb:
        existing_fb.rating = feedback.rating
        existing_fb.comment = feedback.comment
    else:
        new_fb = UserFeedback(
            message_id=str(message_id),
            session_id=str(msg.session_id),
            rating=feedback.rating,
            comment=feedback.comment
        )
        db.add(new_fb)
        
    await db.commit()
    return {"success": True, "message": "Feedback recorded."}


@router.post("/sessions/{session_id}/generate-note")
async def generate_clinical_note(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Generate a SOAP note from the chat history of a session."""
    # Verify session
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Fetch history
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = history_result.scalars().all()
    
    if not messages:
        raise HTTPException(status_code=400, detail="No messages in this session.")

    history_text = ""
    for msg in messages:
        if msg.role in ("user", "assistant"):
            role_name = "Clinician/User" if msg.role == "user" else "AI Assistant"
            history_text += f"**{role_name}:** {msg.content}\n\n"

    from app.services.llm import llm_service
    
    prompt = f"""
You are an expert clinical scribe. Review the following conversation history between a clinician and a clinical AI assistant. 
Based explicitly on the facts and data discussed in this history, generate a comprehensive and professional clinical note. 
Format the output as a standard SOAP note (Subjective, Objective, Assessment, Plan) using Markdown. 
Do not hallucinate information that was not discussed in the chat.

Conversation History:
{history_text}

Output ONLY the formatted Markdown note.
"""
    
    try:
        note_markdown = await llm_service.generate(prompt)
        # Clean up any markdown blocks if generated
        clean_note = note_markdown.strip()
        if clean_note.startswith("```md"):
            clean_note = clean_note[5:]
        elif clean_note.startswith("```markdown"):
            clean_note = clean_note[11:]
        if clean_note.endswith("```"):
            clean_note = clean_note[:-3]
            
        return {"note": clean_note.strip()}
    except Exception as e:
        logger.error(f"Failed to generate clinical note: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate note from LLM.")


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
