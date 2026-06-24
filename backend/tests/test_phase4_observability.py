"""
Phase 4 observability, privacy, and evaluation endpoint tests.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys
import types
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api import admin, chat, evaluations, health
from app.core.metrics import configure_metrics, mark_agent_run, mark_chat_request, mark_document_upload
from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.models.evaluation import EvaluationRun
from app.models.user_feedback import UserFeedback
from app.models.workflow import Workflow
from app.services.evaluation_runner import (
    DEFAULT_CLINICAL_EVAL_SET,
    INTERNAL_EVALUATION_TYPE,
    evaluation_runner_service,
)
from app.services.llm import LLMResponse
from app.services.rag import ContextBundle, ContextItem, RAGAnswer, rag_service
from app.services.vector_store import QdrantBackend
from app.worker import celery_app
from app.core.auth import AuthService


@pytest.fixture
async def phase4_db(tmp_path):
    from app.models.user import User as DBUser

    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "phase4.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["PYTHONPATH"] = str(backend_dir)
    subprocess.run(
        [str(backend_dir / ".venv" / "bin" / "alembic"), "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        check=True,
    )

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        session.add_all(
            [
                DBUser(
                    id="demo-admin-001",
                    email="admin@clinicalgraph.ai",
                    name="Dr. Admin",
                    role="admin",
                    password_hash=AuthService._hash_password("admin123"),
                    is_active=True,
                    is_verified=True,
                ),
                DBUser(
                    id="demo-physician-001",
                    email="physician@clinicalgraph.ai",
                    name="Dr. Physician",
                    role="physician",
                    password_hash=AuthService._hash_password("physician123"),
                    is_active=True,
                    is_verified=True,
                ),
            ]
        )
        await session.commit()

    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.fixture
async def phase4_admin_token(phase4_db) -> str:
    from app.core.auth import auth_service

    async with phase4_db() as session:
        result = await auth_service.authenticate_async(session, "admin@clinicalgraph.ai", "admin123")
        await session.commit()
        assert result is not None
        return result.access_token


@pytest.fixture
async def evaluation_app(phase4_db):
    from app.core.auth import User

    app = FastAPI()
    app.include_router(evaluations.router, prefix="/api")

    async def override_get_db():
        async with phase4_db() as session:
            yield session

    async def override_admin_user() -> User:
        return User(
            id="demo-admin-001",
            email="admin@clinicalgraph.ai",
            name="Dr. Admin",
            role="admin",
            created_at=datetime.now(timezone.utc).isoformat(),
            session_id="phase4-eval-session",
        )

    async def override_physician_user() -> User:
        return User(
            id="demo-physician-001",
            email="physician@clinicalgraph.ai",
            name="Dr. Physician",
            role="physician",
            created_at=datetime.now(timezone.utc).isoformat(),
            session_id="phase4-eval-reader-session",
        )

    app.dependency_overrides[evaluations.get_db] = override_get_db
    app.dependency_overrides[evaluations.require_admin] = override_admin_user
    app.dependency_overrides[evaluations.evaluation_reader] = override_physician_user
    app.dependency_overrides[evaluations.evaluation_reviewer] = override_physician_user
    yield app


@pytest.fixture
async def admin_app(phase4_db):
    app = FastAPI()
    app.include_router(admin.router, prefix="/api")

    async def override_get_db():
        async with phase4_db() as session:
            yield session

    app.dependency_overrides[admin.get_db] = override_get_db
    yield app


@pytest.fixture
async def empty_admin_app(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "phase4_bootstrap.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["PYTHONPATH"] = str(backend_dir)
    subprocess.run(
        [str(backend_dir / ".venv" / "bin" / "alembic"), "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        check=True,
    )

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(admin.router, prefix="/api")

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[admin.get_db] = override_get_db
    try:
        yield app
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_evaluation_runner_generates_required_internal_metrics():
    report = await evaluation_runner_service.run_ragas_eval(DEFAULT_CLINICAL_EVAL_SET[:2])

    assert {
        "answer_groundedness",
        "citation_correctness",
        "retrieval_precision",
        "retrieval_recall_proxy",
        "clinician_acceptance_rate",
        "hallucination_rate",
        "overall_score",
        "faithfulness",
        "answer_relevancy",
        "context_recall",
        "context_precision",
    }.issubset(set(report.metrics))
    assert report.quality_gate["passed"] is True
    assert report.dataset_size == 2
    assert len(report.cases) == 2


@pytest.mark.anyio
async def test_evaluations_latest_and_run_routes(evaluation_app, phase4_db, phase4_admin_token, monkeypatch):
    async with phase4_db() as session:
        session.add(
            EvaluationRun(
                evaluation_type=INTERNAL_EVALUATION_TYPE,
                dataset_size=10,
                metrics={
                    "answer_groundedness": 0.91,
                    "citation_correctness": 0.88,
                    "retrieval_precision": 0.79,
                    "retrieval_recall_proxy": 0.84,
                    "clinician_acceptance_rate": 0.86,
                    "hallucination_rate": 0.08,
                    "overall_score": 0.87,
                    "faithfulness": 0.91,
                    "answer_relevancy": 0.82,
                    "context_recall": 0.84,
                    "context_precision": 0.79,
                },
                metadata_={
                    "runner": "internal_quality_suite",
                    "status": "completed",
                    "job_id": "job-123",
                    "quality_gate": {"passed": True, "release_blocked": False, "regressions": []},
                    "baseline": {"source": "default_thresholds"},
                    "case_results": [
                        {
                            "case_id": "document-bacteremia-001",
                            "category": "document_qa",
                            "question": "Test question",
                            "ground_truth": "Expected",
                            "answer": "Actual",
                            "answer_groundedness": 0.9,
                            "citation_correctness": 0.8,
                            "retrieval_recall_proxy": 0.6,
                            "hallucination_rate": 0.1,
                            "faithfulness": 0.9,
                            "context_recall": 0.6,
                            "context_precision": 0.9,
                        }
                    ],
                },
            )
        )
        await session.commit()

    dispatched: list[str] = []
    async def dispatch(job_id: str):
        dispatched.append(job_id)
        return {"id": job_id}

    monkeypatch.setattr(evaluations, "dispatch_evaluation_run", dispatch)

    transport = ASGITransport(app=evaluation_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {phase4_admin_token}"},
    ) as client:
        latest_response = await client.get("/api/evaluations/latest")
        run_response = await client.post("/api/evaluations/run")

    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["metrics"]["answer_groundedness"] == 0.91
    assert latest_payload["cases"][0]["question"] == "Test question"
    assert latest_payload["quality_gate"]["passed"] is True

    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["status"] == "started"
    assert run_payload["evaluation_type"] == INTERNAL_EVALUATION_TYPE
    assert dispatched == [run_payload["job_id"]]


@pytest.mark.anyio
async def test_evaluation_baseline_and_review_routes(evaluation_app, phase4_db):
    async with phase4_db() as session:
        run = EvaluationRun(
            evaluation_type=INTERNAL_EVALUATION_TYPE,
            dataset_size=2,
            metrics={
                "answer_groundedness": 0.89,
                "citation_correctness": 0.87,
                "retrieval_precision": 0.78,
                "retrieval_recall_proxy": 0.85,
                "clinician_acceptance_rate": 0.75,
                "hallucination_rate": 0.09,
                "overall_score": 0.84,
                "faithfulness": 0.89,
                "answer_relevancy": 0.8,
                "context_recall": 0.85,
                "context_precision": 0.78,
            },
            metadata_={
                "suite_name": "clinical_internal_quality",
                "suite_version": "2026-03-26",
                "case_results": [
                    {
                        "case_id": "document-bacteremia-001",
                        "question": "Test question",
                        "ground_truth": "Expected",
                        "answer": "Actual",
                    }
                ],
            },
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = str(run.id)

    transport = ASGITransport(app=evaluation_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        baseline_response = await client.post(
            f"/api/evaluations/{run_id}/baseline",
            json={"note": "release candidate"},
        )
        review_response = await client.post(
            f"/api/evaluations/{run_id}/review",
            json={
                "case_id": "document-bacteremia-001",
                "accepted": False,
                "tags": ["citation_miss"],
                "notes": "Needs better evidence selection.",
                "correction_action": "adjust_retrieval_prompt",
            },
        )
        fetch_baseline = await client.get("/api/evaluations/baseline")

    assert baseline_response.status_code == 200
    assert baseline_response.json()["baseline"]["is_blessed"] is True

    assert review_response.status_code == 200
    reviewed_payload = review_response.json()
    assert reviewed_payload["review_summary"]["reviewed_cases"] == 1
    assert reviewed_payload["metrics"]["clinician_acceptance_rate"] == 0.0

    assert fetch_baseline.status_code == 200
    assert fetch_baseline.json()["id"] == run_id


@pytest.mark.anyio
async def test_metrics_endpoint_exposes_required_metrics():
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    configure_metrics(app)
    mark_chat_request()
    mark_document_upload()
    mark_agent_run()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/ping")
        response = await client.get("/metrics")

    assert response.status_code == 200
    text = response.text
    assert "http_request_duration_seconds" in text
    assert "chat_requests_total" in text
    assert "document_uploads_total" in text
    assert "agent_runs_total" in text
    assert "rag_retrieval_latency_seconds" in text


@pytest.mark.anyio
async def test_chat_request_counter_increments_on_chat_sync(phase4_db, phase4_admin_token, monkeypatch):
    from app.core.auth import User

    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    configure_metrics(app)

    async def override_get_db():
        async with phase4_db() as session:
            yield session

    async def override_authenticated_user() -> User:
        return User(
            id="demo-admin-001",
            email="admin@clinicalgraph.ai",
            name="Dr. Admin",
            role="admin",
            created_at=datetime.now(timezone.utc).isoformat(),
            session_id="phase4-chat-session",
        )

    app.dependency_overrides[chat.get_db] = override_get_db
    app.dependency_overrides[chat.require_authenticated_user] = override_authenticated_user

    async def fake_execute_sync(_db, _request, _user):
        return {
            "answer": "ok",
            "sources": [],
            "citations": [],
            "reasoning_steps": [],
            "trace": {},
            "error": False,
            "session_id": "session-1",
            "message_id": "message-1",
            "heuristic_evidence_support_score": 0.9,
            "confidence_score": 0.9,
            "confidence_score_deprecated": True,
            "model_used": "test:model",
            "clinician_review_required": True,
        }

    monkeypatch.setattr(chat.chat_orchestrator, "execute_sync", fake_execute_sync)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {phase4_admin_token}"},
    ) as client:
        response = await client.post("/api/chat/sync", json={"message": "hello"})
        metrics = await client.get("/metrics")

    assert response.status_code == 200
    assert "chat_requests_total" in metrics.text


def _build_chat_app(phase4_db):
    from app.core.auth import User

    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    configure_metrics(app)

    async def override_get_db():
        async with phase4_db() as session:
            yield session

    async def override_authenticated_user() -> User:
        return User(
            id="demo-admin-001",
            email="admin@clinicalgraph.ai",
            name="Dr. Admin",
            role="admin",
            created_at=datetime.now(timezone.utc).isoformat(),
            session_id="phase4-chat-session",
        )

    app.dependency_overrides[chat.get_db] = override_get_db
    app.dependency_overrides[chat.require_authenticated_user] = override_authenticated_user
    return app


@pytest.mark.anyio
async def test_chat_sync_and_stream_share_the_same_answer_and_trace(phase4_db, phase4_admin_token, monkeypatch):
    app = _build_chat_app(phase4_db)

    async def fake_bundle(_db, request, _user):
        return ContextBundle(
            mode="retrieval",
            query=request.message,
            expanded_queries=[],
            items=[
                ContextItem(
                    citation_id="SRC1",
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    document_name="Guideline",
                    chunk_index=0,
                    chunk_text="Grounded evidence.",
                    retrieval_score=0.95,
                )
            ],
            context_text="[SRC1] Source=Guideline | ChunkID=chunk-1 | Page=n/a\nGrounded evidence.",
            reasoning_steps=[
                {"step": 1, "title": "Retrieval", "description": "Loaded grounded evidence.", "status": "done"}
            ],
            retrieval_method="hybrid",
            total_candidates=1,
            retrieval_latency_ms=9.0,
            context_policy={"top_k": 1},
        )

    async def fake_generate_answer(*, question, bundle, chat_history=None):
        return RAGAnswer(
            answer="Grounded answer [SRC1]",
            sources=[bundle.items[0].source_reference()],
            citations=[
                {
                    "marker": "SRC1",
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "document_name": "Guideline",
                    "page_reference": None,
                    "span_start": 16,
                    "span_end": 22,
                }
            ],
            reasoning_steps=bundle.reasoning_steps,
            trace={"query": question, "retrieved_chunks": [{"chunk_id": "chunk-1"}]},
            heuristic_evidence_support_score=0.91,
            model_used="test:model",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            clinician_review_required=True,
        )

    monkeypatch.setattr(chat.chat_orchestrator, "_resolve_bundle", fake_bundle)
    monkeypatch.setattr(rag_service, "generate_answer", fake_generate_answer)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {phase4_admin_token}"},
    ) as client:
        sync_response = await client.post("/api/chat/sync", json={"message": "hello"})

        streamed_tokens: list[str] = []
        streamed_sources = None
        streamed_trace = None
        streamed_event_types: list[str] = []
        async with client.stream("POST", "/api/chat", json={"message": "hello"}) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                streamed_event_types.append(payload["type"])
                if payload["type"] == "token":
                    streamed_tokens.append(payload["content"])
                elif payload["type"] == "source":
                    streamed_sources = payload["sources"]
                elif payload["type"] == "trace":
                    streamed_trace = payload["trace"]

    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["answer"] == "".join(streamed_tokens)
    assert sync_payload["sources"] == streamed_sources
    assert sync_payload["trace"]["trace_level"] == "public"
    assert streamed_trace["trace_level"] == "public"
    assert "query" not in sync_payload["trace"]
    assert "retrieved_chunks" not in sync_payload["trace"]
    assert "final_context" not in sync_payload["trace"]
    assert sync_payload["trace"]["retrieved_chunk_count"] == streamed_trace["retrieved_chunk_count"]
    assert sync_payload["trace"]["ready_to_stream"] is True
    assert streamed_trace["ready_to_stream"] is True
    assert "STREAMING" in {entry["state"] for entry in streamed_trace["state_transitions"]}
    assert streamed_event_types[0] == "reasoning"

    async with phase4_db() as session:
        result = await session.execute(select(ChatMessage).where(ChatMessage.role == "assistant"))
        saved_messages = result.scalars().all()
        assert len(saved_messages) == 2
        assert all(message.metadata_["trace"]["trace_level"] == "internal_metadata_only" for message in saved_messages)
        assert all("query" not in message.metadata_["trace"] for message in saved_messages)


@pytest.mark.anyio
async def test_chat_history_returns_public_metadata_and_sanitized_sources(phase4_db, phase4_admin_token):
    app = _build_chat_app(phase4_db)
    session_id = uuid.uuid4()

    async with phase4_db() as session:
        session.add(ChatSession(id=session_id, user_id="demo-admin-001", title="Public history"))
        session.add(
            ChatMessage(
                session_id=session_id,
                role="assistant",
                content="Grounded answer [SRC1]",
                sources=[
                    {
                        "citation_id": "SRC1",
                        "chunk_id": "chunk-secret",
                        "document_id": "doc-1",
                        "document_name": "note.txt",
                        "chunk_index": 0,
                        "text": "raw patient chunk text",
                        "chunk_text": "raw patient chunk text",
                        "relevance_score": 0.9,
                    }
                ],
                metadata_={
                    "heuristic_evidence_support_score": 0.8,
                    "trace": {
                        "trace_level": "internal_full",
                        "query": "patient-specific private query",
                        "final_context": "raw final context",
                        "retrieved_chunks": [{"chunk_id": "chunk-secret", "text": "raw patient chunk text"}],
                        "guardrails": {"clinician_review_required": True},
                    },
                },
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {phase4_admin_token}"},
    ) as client:
        response = await client.get(f"/api/chat/sessions/{session_id}")

    assert response.status_code == 200
    message = response.json()["messages"][0]
    assert message["metadata"]["trace"]["trace_level"] == "public"
    rendered = json.dumps(message)
    assert "internal_full" not in rendered
    assert "patient-specific private query" not in rendered
    assert "raw final context" not in rendered
    assert "raw patient chunk text" not in rendered
    assert "text" not in message["sources"][0]
    assert "chunk_text" not in message["sources"][0]
    assert message["sources"][0]["chunk_id"] == "chunk-secret"


@pytest.mark.anyio
async def test_chat_sync_supports_attached_document_with_citations(phase4_db, phase4_admin_token, monkeypatch):
    app = _build_chat_app(phase4_db)
    document_id = uuid.uuid4()

    async with phase4_db() as session:
        session.add(
            Document(
                id=document_id,
                user_id="demo-admin-001",
                filename="protocol.pdf",
                content_hash="doc-hash-chat",
                file_size=100,
                file_type="pdf",
                content_type="application/pdf",
                chunk_count=1,
                status="ready",
                processing_stage="ready",
                processing_progress=100,
                metadata_={"original_suffix": ".pdf"},
            )
        )
        await session.commit()

    monkeypatch.setattr(
        "app.services.chat_orchestrator.vector_store_service.get_chunks_for_document",
        lambda *_args, **_kwargs: [
            {
                "chunk_id": "doc-chunk-1",
                "chunk_index": 0,
                "chunk_text": "Use protocolized follow-up for the next 48 hours.",
                "document_id": str(document_id),
                "document_name": "protocol.pdf",
                "page_start": 2,
                "page_end": 2,
            }
        ],
    )

    async def fake_generate_with_metadata(*_args, **_kwargs):
        return LLMResponse(
            text="Follow the 48-hour protocolized follow-up [DOC1]\n[CONFIDENCE: 0.88]",
            provider="test",
            model_used="unit",
            token_usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        )

    monkeypatch.setattr("app.services.llm.llm_service.generate_with_metadata", fake_generate_with_metadata)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {phase4_admin_token}"},
    ) as client:
        response = await client.post(
            "/api/chat/sync",
            json={"message": "What should I do?", "attached_document_id": str(document_id)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("Follow the 48-hour protocolized follow-up")
    assert payload["sources"][0]["chunk_id"] == "doc-chunk-1"
    assert payload["sources"][0]["page_reference"] == "p. 2"
    assert payload["citations"][0]["marker"] == "DOC1"
    assert payload["trace"]["retrieved_chunk_count"] == 1
    assert "retrieved_chunks" not in payload["trace"]


@pytest.mark.anyio
async def test_chat_sync_rejects_attached_document_until_ready(phase4_db, phase4_admin_token):
    app = _build_chat_app(phase4_db)
    document_id = uuid.uuid4()

    async with phase4_db() as session:
        session.add(
            Document(
                id=document_id,
                user_id="demo-admin-001",
                filename="pending.pdf",
                content_hash="doc-hash-pending",
                file_size=100,
                file_type="pdf",
                content_type="application/pdf",
                chunk_count=0,
                status="queued",
                processing_stage="chunked",
                processing_progress=40,
                metadata_={"original_suffix": ".pdf"},
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {phase4_admin_token}"},
    ) as client:
        response = await client.post(
            "/api/chat/sync",
            json={"message": "Summarize it", "attached_document_id": str(document_id)},
        )

    assert response.status_code == 409
    assert "still processing" in response.json()["detail"]


@pytest.mark.anyio
async def test_generate_note_persists_traceable_note_metadata(phase4_db, phase4_admin_token, monkeypatch):
    app = _build_chat_app(phase4_db)
    session_id = uuid.uuid4()

    async with phase4_db() as session:
        session.add(ChatSession(id=session_id, user_id="demo-admin-001", title="Traceable note"))
        session.add_all(
            [
                ChatMessage(session_id=session_id, role="user", content="Patient reports headache."),
                ChatMessage(session_id=session_id, role="assistant", content="Headache has been present for 2 days."),
            ]
        )
        await session.commit()

    async def fake_note_generate(_prompt: str):
        return {
            "text": "```markdown\n# SOAP Note\n\nSubjective: Headache for 2 days.\n```",
            "model_used": "test:model",
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17},
        }

    monkeypatch.setattr("app.services.chat_orchestrator.visionless_llm_generate", fake_note_generate)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {phase4_admin_token}"},
    ) as client:
        response = await client.post(f"/api/chat/sessions/{session_id}/generate-note")

    assert response.status_code == 200
    payload = response.json()
    assert payload["note"].startswith("# SOAP Note")

    async with phase4_db() as session:
        result = await session.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.desc())
        )
        saved_note = result.scalars().first()
        assert saved_note is not None
        assert saved_note.metadata_["message_kind"] == "clinical_note"
        assert saved_note.metadata_["prompt_version"] == "clinical-note-v1"
        assert saved_note.metadata_["clinician_review_required"] is True
        assert len(saved_note.metadata_["generated_from_message_ids"]) == 2


@pytest.mark.anyio
async def test_health_detailed_returns_all_services(monkeypatch):
    app = FastAPI()
    app.include_router(health.router, prefix="/api")

    async def fake_db_health():
        return {"status": "healthy"}

    async def fake_redis_health():
        return {"status": "healthy"}

    async def fake_neo4j_health():
        return {"status": "disabled"}

    async def fake_llm_health(timeout_seconds=5.0):
        return {"status": "not_configured", "provider": "gemini"}

    async def fake_migration_status():
        return {"status": "current", "current_revision": "head", "head_revision": "head"}

    async def fake_queue_depths():
        return {"document_processing": 1}

    monkeypatch.setattr(health, "check_db_health", fake_db_health)
    monkeypatch.setattr(health, "check_migration_status", fake_migration_status)
    monkeypatch.setattr(health, "refresh_worker_queue_depths", fake_queue_depths)
    monkeypatch.setattr(health.redis_service, "health_check", fake_redis_health)
    monkeypatch.setattr(health, "check_neo4j_health", fake_neo4j_health)
    monkeypatch.setattr(health.llm_service, "health_check", fake_llm_health)
    monkeypatch.setattr(health.vector_store_service, "get_stats", lambda: {"backend": "faiss", "total_chunks": 2})
    monkeypatch.setattr(health, "background_jobs_health", lambda: {"status": "disabled", "transport": "local"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health/detailed")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["services"]["migrations"]["status"] == "healthy"
    assert payload["services"]["background_jobs"]["queue_depth"] == {"document_processing": 1}
    assert set(payload["services"]) == {
        "postgres",
        "migrations",
        "redis",
        "neo4j",
        "vector_store",
        "llm_provider",
        "background_jobs",
    }


@pytest.mark.anyio
async def test_admin_metrics_returns_dashboard_rollups(phase4_db, monkeypatch):
    from app.core.auth import User

    app = FastAPI()
    app.include_router(admin.router, prefix="/api")

    async def override_get_db():
        async with phase4_db() as session:
            yield session

    async def override_admin_user() -> User:
        return User(
            id="demo-admin-001",
            email="admin@clinicalgraph.ai",
            name="Dr. Admin",
            role="admin",
            created_at=datetime.now(timezone.utc).isoformat(),
            session_id="phase4-admin-session",
        )

    async def fake_dashboard_metrics():
        return {
            "chat_latency_ms_avg": 12.5,
            "retrieval_latency_ms_avg": 8.1,
            "llm_failure_rate": 0.0,
            "document_processing_failure_rate": 0.0,
            "image_analysis_success_rate": 1.0,
            "worker_queue_depth": {"document_processing": 2},
        }

    monkeypatch.setattr(admin, "collect_operational_metrics_summary", fake_dashboard_metrics)
    app.dependency_overrides[admin.get_db] = override_get_db
    app.dependency_overrides[admin.require_admin] = override_admin_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert "total_requests" in payload
    assert payload["dashboard_metrics"]["chat_latency_ms_avg"] == 12.5
    assert payload["dashboard_metrics"]["worker_queue_depth"] == {"document_processing": 2}


@pytest.mark.anyio
async def test_auth_bootstrap_creates_first_admin_once(empty_admin_app):
    transport = ASGITransport(app=empty_admin_app)
    payload = {
        "email": "admin@clinicalgraph.ai",
        "password": "admin12345",
        "name": "Dr. First Admin",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/auth/bootstrap", json=payload)
        second = await client.post("/api/auth/bootstrap", json=payload)

    assert first.status_code == 200
    data = first.json()
    assert data["user"]["role"] == "admin"
    assert data["user"]["email"] == "admin@clinicalgraph.ai"
    assert "access_token" in data
    assert second.status_code == 409
    assert second.json()["detail"] == "Users already exist; bootstrap is closed"


@pytest.mark.anyio
async def test_gdpr_export_and_purge(admin_app, phase4_db, phase4_admin_token, monkeypatch):
    target_user = "demo-physician-001"
    session_id = uuid.uuid4()

    async with phase4_db() as session:
        session.add(
            ChatSession(
                id=session_id,
                user_id=target_user,
                title="Session",
            )
        )
        session.add(
            ChatMessage(
                session_id=session_id,
                role="user",
                content="Hello",
            )
        )
        session.add(
            Document(
                user_id=target_user,
                filename="note.pdf",
                content_hash="hash-1",
                file_size=100,
                file_type="pdf",
                metadata_={"original_suffix": ".pdf"},
            )
        )
        session.add(
            Workflow(
                user_id=target_user,
                session_id=session_id,
                workflow_type="general",
                status="completed",
            )
        )
        session.add(
            UserFeedback(
                user_id=target_user,
                message_id="msg-1",
                session_id=str(session_id),
                rating=5,
                comment="good",
            )
        )
        session.add(
            AuditLog(
                user_id=target_user,
                action="CHAT_QUERY",
                resource_type="chat",
                resource_id=str(session_id),
            )
        )
        await session.commit()

    monkeypatch.setattr(admin, "purge_user_data", admin.purge_user_data)
    monkeypatch.setattr(
        sys.modules["app.services.vector_store"].vector_store_service,
        "mark_document_deleted",
        lambda _document_id: 1,
    )
    monkeypatch.setattr(
        sys.modules["app.services.bm25_index"].bm25_index,
        "mark_document_deleted",
        lambda _document_id: 1,
    )
    monkeypatch.setattr(
        sys.modules["app.services.image_processing"].image_processing_service,
        "delete_image",
        lambda *_args, **_kwargs: None,
    )

    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {phase4_admin_token}"},
    ) as client:
        export_response = await client.post(f"/api/admin/gdpr/export/{target_user}")
        purge_response = await client.delete(f"/api/admin/gdpr/purge/{target_user}")

    assert export_response.status_code == 200
    export_payload = export_response.json()
    assert export_payload["user_id"] == target_user
    assert len(export_payload["sessions"]) == 1
    assert len(export_payload["documents"]) == 1
    assert len(export_payload["audit_logs"]) == 1

    assert purge_response.status_code == 200
    purge_payload = purge_response.json()
    assert purge_payload["deleted"]["sessions"] == 1
    assert purge_payload["deleted"]["documents"] == 1
    assert purge_payload["deleted"]["vector_tombstones"] == 1
    assert purge_payload["deleted"]["bm25_tombstones"] == 1

    async with phase4_db() as session:
        remaining_sessions = await session.execute(select(ChatSession))
        remaining_documents = await session.execute(select(Document))
    assert remaining_sessions.scalars().all() == []
    assert remaining_documents.scalars().all() == []


def test_qdrant_backend_connects_with_fake_client(monkeypatch):
    settings = get_settings()
    original_url = settings.qdrant_url
    original_collection = settings.qdrant_collection

    class FakeCollections:
        collections = []

    class FakeCollectionInfo:
        vectors_count = 4
        points_count = 4

    class FakeQdrantClient:
        def __init__(self, url, api_key=None):
            self.url = url
            self.api_key = api_key

        def get_collections(self):
            return FakeCollections()

        def create_collection(self, **_kwargs):
            return None

        def get_collection(self, _collection_name):
            return FakeCollectionInfo()

        def scroll(self, **_kwargs):
            return ([], None)

    fake_models = types.SimpleNamespace(
        VectorParams=lambda **kwargs: kwargs,
        Distance=types.SimpleNamespace(COSINE="cosine"),
        Filter=lambda **kwargs: kwargs,
        FieldCondition=lambda **kwargs: kwargs,
        MatchValue=lambda **kwargs: kwargs,
        PointStruct=lambda **kwargs: kwargs,
        FilterSelector=lambda **kwargs: kwargs,
    )
    fake_module = types.SimpleNamespace(QdrantClient=FakeQdrantClient, models=fake_models)

    monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)
    settings.qdrant_url = "http://fake-qdrant"
    settings.qdrant_collection = "clinical_phase4"

    backend = QdrantBackend()
    stats = backend.get_stats()

    settings.qdrant_url = original_url
    settings.qdrant_collection = original_collection

    assert stats["backend"] == "qdrant"
    assert stats["total_chunks"] == 4


def test_retention_task_registered_in_celery_schedule():
    assert celery_app is not None
    assert "purge-expired-data-nightly" in celery_app.conf.beat_schedule
