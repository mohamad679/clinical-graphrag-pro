"""
Unified chat orchestration for sync, streaming, document, and image grounded turns.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import User
from app.core.config import get_settings
from app.core.error_envelope import log_internal_error, safe_error_envelope
from app.core.metrics import observe_chat_latency
from app.core.observability import bind_observability_context, trace_operation
from app.core.retrieval_scope import retrieval_scope_for_user
from app.core.trace_sanitizer import (
    build_debug_redacted_trace,
    build_internal_audit_trace,
    build_public_trace,
    sanitize_source_references,
)
from app.core.redis import redis_service
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.models.medical_image import MedicalImage
from app.schemas.chat import ChatRequest
from app.services.chat_state import ChatState, ChatStateMachine
from app.services.image_processing import image_processing_service
from app.services.rag import (
    CHAT_ANSWER_STYLE_VERSION,
    CHAT_NOTE_PROMPT_VERSION,
    CHAT_SYSTEM_PROMPT_VERSION,
    CHAT_TITLE_POLICY_VERSION,
    ContextBundle,
    RAGAnswer,
    rag_service,
)
from app.services.vector_store import vector_store_service
from app.services.vision import vision_service

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(slots=True)
class PreparedChatTurn:
    session_id: UUID
    user_message_id: UUID
    question: str
    chat_history: list[dict]
    history_message_ids: list[str]
    bundle: ContextBundle
    attached_document_id: str | None
    attached_image_id: str | None
    session_title: str


class ChatOrchestrator:
    """Owns turn preparation, grounding, generation, and persistence."""

    async def prepare_turn(
        self,
        db: AsyncSession,
        request: ChatRequest,
        user: User,
    ) -> PreparedChatTurn:
        session = await self._resolve_session(db, request, user)
        history_rows = await self._load_history(db, session.id)
        chat_history = [
            {"role": row.role, "content": row.content}
            for row in history_rows[-settings.chat_history_message_limit :]
            if row.role in {"user", "assistant"}
            and not ((row.metadata_ or {}).get("message_kind") == "clinical_note")
        ]
        history_message_ids = [str(row.id) for row in history_rows if row.role in {"user", "assistant"}]

        bundle = await self._resolve_bundle(db, request, user)

        session.updated_at = datetime.now(timezone.utc)
        session.metadata_ = {
            **(session.metadata_ or {}),
            "system_prompt_version": CHAT_SYSTEM_PROMPT_VERSION,
            "answer_style_version": CHAT_ANSWER_STYLE_VERSION,
            "title_policy_version": CHAT_TITLE_POLICY_VERSION,
            "note_prompt_version": CHAT_NOTE_PROMPT_VERSION,
            "history_message_limit": settings.chat_history_message_limit,
        }

        user_message = ChatMessage(
            session_id=session.id,
            role="user",
            content=request.message,
            metadata_={
                "mode": bundle.mode,
                "attached_document_id": str(request.attached_document_id) if request.attached_document_id else None,
                "attached_image_id": str(request.attached_image_id) if request.attached_image_id else None,
            },
        )
        db.add(user_message)
        await db.flush()
        await db.commit()

        return PreparedChatTurn(
            session_id=session.id,
            user_message_id=user_message.id,
            question=request.message,
            chat_history=chat_history,
            history_message_ids=history_message_ids,
            bundle=bundle,
            attached_document_id=str(request.attached_document_id) if request.attached_document_id else None,
            attached_image_id=str(request.attached_image_id) if request.attached_image_id else None,
            session_title=session.title,
        )

    async def execute_sync(
        self,
        db: AsyncSession,
        request: ChatRequest,
        user: User,
        *,
        trace_level: str = "public",
        debug_trace_authorized: bool = False,
    ) -> dict:
        started = time.perf_counter()
        state_machine = ChatStateMachine()
        state_machine.transition(ChatState.AUTHENTICATED)
        state_machine.transition(ChatState.SCOPED)
        prepared = await self.prepare_turn(db, request, user)
        state_machine.transition(ChatState.RETRIEVED)
        with bind_observability_context(
            session_id=str(prepared.session_id),
            document_id=prepared.attached_document_id,
            image_id=prepared.attached_image_id,
        ):
            answer, assistant_message_id = await self._run_turn(db, prepared, state_machine=state_machine, stream=False)
        observe_chat_latency(time.perf_counter() - started, mode="sync")
        return self._sync_payload(
            prepared,
            answer,
            assistant_message_id,
            trace_level=trace_level,
            debug_trace_authorized=debug_trace_authorized,
        )

    async def stream(
        self,
        db: AsyncSession,
        request: ChatRequest,
        user: User,
    ) -> AsyncGenerator[dict, None]:
        started = time.perf_counter()
        state_machine = ChatStateMachine()
        try:
            state_machine.transition(ChatState.AUTHENTICATED)
            yield {
                "type": "reasoning",
                "step": 0,
                "title": "Preparing request",
                "description": "Saving your message and checking attachment readiness.",
                "status": "running",
            }
            state_machine.transition(ChatState.SCOPED)
            prepared = await self.prepare_turn(db, request, user)
            state_machine.transition(ChatState.RETRIEVED)
            yield {
                "type": "reasoning",
                "step": 0,
                "title": "Preparing request",
                "description": "Message saved and grounded evidence is ready to use.",
                "status": "done",
            }
            yield {
                "type": "reasoning",
                "step": 99,
                "title": "Generating answer",
                "description": "Building a grounded response from the available evidence.",
                "status": "running",
            }
            with bind_observability_context(
                session_id=str(prepared.session_id),
                document_id=prepared.attached_document_id,
                image_id=prepared.attached_image_id,
            ):
                answer, assistant_message_id = await self._run_turn(
                    db,
                    prepared,
                    state_machine=state_machine,
                    stream=True,
                )
        except HTTPException as exc:
            state_machine.fail()
            detail = exc.detail if isinstance(exc.detail, str) else "The request is not ready to run."
            yield {
                "type": "error",
                "code": "request_not_ready",
                "message": detail,
                "content": detail,
            }
            return
        except Exception as exc:
            state_machine.fail()
            log_internal_error(logger, "chat.turn_failed", exc, error_code="streaming_failed")
            yield {"type": "error", **safe_error_envelope("streaming_failed")}
            return
        observe_chat_latency(time.perf_counter() - started, mode="stream")

        yield {
            "type": "reasoning",
            "step": 99,
            "title": "Generating answer",
            "description": "Grounded response is ready.",
            "status": "done",
        }
        for step in answer.reasoning_steps:
            yield {
                "type": "reasoning",
                "step": step["step"],
                "title": step["title"],
                "description": step["description"],
                "status": step.get("status", "done"),
            }
        if answer.sources:
            yield {
                "type": "source",
                "sources": sanitize_source_references(answer.sources),
                "citations": answer.citations,
            }
        chunk_size = max(settings.chat_stream_chunk_size, 1)
        for start in range(0, len(answer.answer), chunk_size):
            yield {"type": "token", "content": answer.answer[start : start + chunk_size]}
        yield {"type": "trace", "trace": build_public_trace(answer.trace)}
        yield {
            "type": "done",
            "session_id": str(prepared.session_id),
            "message_id": str(assistant_message_id),
        }

    async def generate_note(
        self,
        db: AsyncSession,
        session_id: UUID,
        user: User,
    ) -> dict:
        session = await self._get_session_or_404(db, session_id, user)
        history_rows = await self._load_history(db, session.id)
        messages = [
            row
            for row in history_rows
            if row.role in {"user", "assistant"}
            and not ((row.metadata_ or {}).get("message_kind") == "clinical_note")
        ]
        if not messages:
            raise HTTPException(status_code=400, detail="No messages in this session.")

        history_text = ""
        for msg in messages:
            role_name = "Clinician/User" if msg.role == "user" else "AI Assistant"
            history_text += f"**{role_name}:** {msg.content}\n\n"

        prompt = f"""
You are an expert clinical scribe.
Prompt version: {CHAT_NOTE_PROMPT_VERSION}

Review the conversation history below and generate a SOAP note.
Use only the discussed facts.
Do not hallucinate findings not grounded in the conversation.
Output only the note in Markdown.

Conversation History:
{history_text}
"""

        response = await visionless_llm_generate(prompt)
        clean_note = self._clean_markdown_block(response["text"])

        note_message = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=clean_note,
            model_used=response["model_used"],
            token_count=response["token_usage"].get("completion_tokens"),
            metadata_={
                "message_kind": "clinical_note",
                "generated_from_message_ids": [str(msg.id) for msg in messages],
                "prompt_version": CHAT_NOTE_PROMPT_VERSION,
                "clinician_review_required": True,
                "token_usage": response["token_usage"],
            },
        )
        db.add(note_message)
        session.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(note_message)

        return {
            "note": clean_note,
            "message_id": str(note_message.id),
            "trace": note_message.metadata_,
        }

    async def _resolve_session(
        self,
        db: AsyncSession,
        request: ChatRequest,
        user: User,
    ) -> ChatSession:
        if request.session_id:
            return await self._get_session_or_404(db, request.session_id, user)

        title = self._build_session_title(request.message)
        session = ChatSession(
            title=title,
            user_id=user.id,
            metadata_={
                "system_prompt_version": CHAT_SYSTEM_PROMPT_VERSION,
                "answer_style_version": CHAT_ANSWER_STYLE_VERSION,
                "title_policy_version": CHAT_TITLE_POLICY_VERSION,
                "history_message_limit": settings.chat_history_message_limit,
            },
        )
        db.add(session)
        await db.flush()
        return session

    async def _get_session_or_404(self, db: AsyncSession, session_id: UUID, user: User) -> ChatSession:
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        session = result.scalar_one_or_none()
        if not session or (user.role != "admin" and session.user_id not in {None, user.id}):
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    async def _load_history(self, db: AsyncSession, session_id: UUID) -> list[ChatMessage]:
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        return result.scalars().all()

    async def _resolve_bundle(self, db: AsyncSession, request: ChatRequest, user: User) -> ContextBundle:
        bundles: list[ContextBundle] = []

        if request.attached_document_id:
            doc_result = await db.execute(
                select(Document)
                .options(selectinload(Document.content))
                .where(Document.id == request.attached_document_id)
            )
            document = doc_result.scalar_one_or_none()
            if not document or (user.role != "admin" and document.user_id != user.id):
                raise HTTPException(status_code=404, detail="Attached document not found.")
            if document.status == "error":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=document.error_message or "Attached document processing failed.",
                )
            if document.status != "ready" or document.processing_stage != "ready":
                stage = document.processing_stage or document.status or "processing"
                progress = int(document.processing_progress or 0)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Attached document is still processing ({stage}, {progress}% complete).",
                )

            doc_chunks = vector_store_service.get_chunks_for_document(
                str(request.attached_document_id),
                filters=None if user.role == "admin" else retrieval_scope_for_user(user).to_filters(),
            )
            if not doc_chunks and document.content is not None:
                fallback_text = document.content.normalized_text or document.content.raw_text or ""
                if fallback_text.strip():
                    doc_chunks = [
                        {
                            "chunk_id": f"{document.id}-fallback",
                            "chunk_index": 0,
                            "chunk_text": fallback_text,
                            "document_id": str(document.id),
                            "document_name": document.filename,
                        }
                    ]
            if not doc_chunks:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Attached document is ready but has no indexed content yet.",
                )

            bundles.append(
                rag_service.build_document_bundle(
                    question=request.message,
                    document_id=str(document.id),
                    document_name=document.filename,
                    chunks=doc_chunks,
                )
            )

        if request.attached_image_id:
            image_result = await db.execute(
                select(MedicalImage)
                .options(
                    selectinload(MedicalImage.annotations),
                    selectinload(MedicalImage.storage_asset),
                )
                .where(MedicalImage.id == request.attached_image_id)
            )
            image = image_result.scalar_one_or_none()
            if not image or (user.role != "admin" and image.user_id != user.id):
                raise HTTPException(status_code=404, detail="Attached image not found")

            analysis = image.analysis_result or {}
            if not analysis:
                image_bytes = await image_processing_service.read_image_bytes(image)
                analysis = await vision_service.analyze_image(image_bytes, image.mime_type, "")
                image.analysis_result = analysis
                image.analysis_status = "ai_generated" if "error" not in analysis else "failed"
                image.analyzed_at = datetime.now(timezone.utc)
                image.modality = analysis.get("modality_detected")
                image.body_part = analysis.get("body_part_detected")

            bundles.append(
                rag_service.build_image_bundle(
                    question=request.message,
                    image_id=str(image.id),
                    image_name=image.original_filename,
                    analysis=analysis,
                    annotations=[
                        {
                            "label": annotation.label,
                            "annotation_type": annotation.annotation_type,
                        }
                        for annotation in image.annotations
                    ],
                )
            )

        if bundles:
            if len(bundles) == 1:
                return bundles[0]
            return rag_service.merge_bundles(request.message, bundles)

        return await rag_service.build_retrieval_bundle(
            request.message,
            top_k=settings.top_k,
            scope=retrieval_scope_for_user(user),
        )

    async def _run_turn(
        self,
        db: AsyncSession,
        prepared: PreparedChatTurn,
        *,
        state_machine: ChatStateMachine | None = None,
        stream: bool = False,
    ) -> tuple[RAGAnswer, UUID]:
        if state_machine is None:
            state_machine = ChatStateMachine()
            state_machine.transition(ChatState.AUTHENTICATED)
            state_machine.transition(ChatState.SCOPED)
            state_machine.transition(ChatState.RETRIEVED)
        with trace_operation(
            "chat.turn",
            component="chat",
            logger_=logger,
            session_id=str(prepared.session_id),
            document_id=prepared.attached_document_id,
            image_id=prepared.attached_image_id,
        ):
            answer = await rag_service.generate_answer(
                question=prepared.question,
                bundle=prepared.bundle,
                chat_history=prepared.chat_history,
            )
        state_machine.transition(ChatState.DRAFT_GENERATED)
        state_machine.transition(ChatState.GROUNDING_VALIDATED)
        state_machine.transition(ChatState.POLICY_VALIDATED)
        if self._is_abstention(answer):
            state_machine.transition(ChatState.ABSTAINED)
        state_machine.transition(ChatState.READY_TO_STREAM)
        if stream:
            state_machine.transition(ChatState.STREAMING)
        state_machine.transition(ChatState.COMPLETED)
        answer.trace = {
            **answer.trace,
            "state_transitions": state_machine.trace,
            "ready_to_stream": True,
        }
        assistant_message_id = await self._persist_assistant_message(db, prepared, answer)
        await redis_service.set(
            f"chat:last_response:{prepared.session_id}",
            {
                "answer": answer.answer,
                "sources": sanitize_source_references(answer.sources) or [],
                "citations": answer.citations,
            },
            ttl=1800,
        )
        return answer, assistant_message_id

    @staticmethod
    def _is_abstention(answer: RAGAnswer) -> bool:
        guardrails = answer.trace.get("guardrails", {}) if answer.trace else {}
        return bool(
            answer.model_used.startswith("guardrail:")
            or guardrails.get("insufficient_context")
            or guardrails.get("failed_citation_grounding")
            or "not have enough evidence" in answer.answer.lower()
            or "insufficient evidence" in answer.answer.lower()
        )

    async def _persist_assistant_message(
        self,
        db: AsyncSession,
        prepared: PreparedChatTurn,
        answer: RAGAnswer,
    ) -> UUID:
        db_session = await db.get(ChatSession, prepared.session_id)
        if db_session is None:
            raise RuntimeError("Chat session disappeared before assistant persistence")

        message = ChatMessage(
            session_id=prepared.session_id,
            role="assistant",
            content=answer.answer,
            sources=sanitize_source_references(answer.sources) or [],
            reasoning_steps=answer.reasoning_steps,
            token_count=answer.token_usage.get("completion_tokens"),
            model_used=answer.model_used,
            confidence_score=answer.confidence_score,
            metadata_={
                "mode": prepared.bundle.mode,
                "attached_document_id": prepared.attached_document_id,
                "attached_image_id": prepared.attached_image_id,
                "generated_from_message_ids": prepared.history_message_ids + [str(prepared.user_message_id)],
                "clinician_review_required": answer.clinician_review_required,
                "heuristic_evidence_support_score": answer.heuristic_evidence_support_score,
                "confidence_score_deprecated": True,
                "trace": build_internal_audit_trace(
                    answer.trace,
                    full_enabled=bool(get_settings().internal_full_trace_enabled),
                ),
            },
        )
        db.add(message)
        db_session.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(message)
        return message.id

    def _sync_payload(
        self,
        prepared: PreparedChatTurn,
        answer: RAGAnswer,
        assistant_message_id: UUID,
        *,
        trace_level: str = "public",
        debug_trace_authorized: bool = False,
    ) -> dict:
        if trace_level == "debug_redacted" and debug_trace_authorized:
            trace = build_debug_redacted_trace(answer.trace)
        else:
            trace = build_public_trace(answer.trace)
        return {
            "answer": answer.answer,
            "sources": sanitize_source_references(answer.sources) or [],
            "citations": answer.citations,
            "reasoning_steps": answer.reasoning_steps,
            "trace": trace,
            "error": answer.error,
            "session_id": str(prepared.session_id),
            "message_id": str(assistant_message_id),
            "heuristic_evidence_support_score": answer.heuristic_evidence_support_score,
            "confidence_score": answer.confidence_score,
            "confidence_score_deprecated": True,
            "model_used": answer.model_used,
            "clinician_review_required": answer.clinician_review_required,
        }

    @staticmethod
    def _build_session_title(message: str) -> str:
        compact = " ".join(message.strip().split())
        if not compact:
            return "New Chat"
        if len(compact) <= 80:
            return compact
        return compact[:77].rstrip() + "..."

    @staticmethod
    def _clean_markdown_block(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```md"):
            cleaned = cleaned[5:]
        elif cleaned.startswith("```markdown"):
            cleaned = cleaned[11:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()


async def visionless_llm_generate(prompt: str) -> dict:
    from app.services.llm import llm_service

    response = await llm_service.generate_with_metadata(
        prompt,
        context="",
        chat_history=None,
        system_prompt=(
            "You are an expert clinical scribe. Generate only grounded SOAP notes and do not hallucinate."
        ),
    )
    return {
        "text": response.text,
        "model_used": f"{response.provider}:{response.model_used}",
        "token_usage": response.token_usage,
    }


chat_orchestrator = ChatOrchestrator()
