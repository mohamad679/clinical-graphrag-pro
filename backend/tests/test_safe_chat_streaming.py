import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from app.api import admin, chat
from app.core.auth import User, require_authenticated_user
from app.core.config import Settings
from app.core.database import async_session_factory, get_db
from app.models.chat import ChatSession
from app.services.agent import AgentOrchestrator
from app.services.chat_state import ChatState, ChatStateMachine
from app.services.llm import LLMResponse, llm_service
from app.services.rag import ContextBundle, ContextItem, rag_service


def _safe_settings_kwargs() -> dict:
    return {
        "jwt_secret": "test-secret-for-safe-streaming-0123456789",
        "debug": False,
        "app_env": "development",
        "llm_provider": "retrieval-only",
        "_env_file": None,
    }


def _bundle() -> ContextBundle:
    item = ContextItem(
        citation_id="SRC1",
        chunk_id="c1",
        document_id="doc1",
        document_name="doc.txt",
        chunk_index=0,
        chunk_text="Amlodipine 5 mg daily was prescribed for hypertension.",
        retrieval_score=0.9,
    )
    return ContextBundle(
        mode="retrieval",
        query="What medication was prescribed?",
        expanded_queries=[],
        items=[item],
        context_text="[SRC1] Amlodipine 5 mg daily was prescribed for hypertension.",
        reasoning_steps=[
            {
                "step": 1,
                "title": "Retrieve",
                "description": "Retrieved grounded evidence.",
                "status": "done",
            }
        ],
        retrieval_method="dense",
        total_candidates=1,
        retrieval_latency_ms=0.0,
        context_policy={},
    )


def _attached_document_bundle() -> ContextBundle:
    items = [
        ContextItem(
            citation_id="DOC1",
            chunk_id="doc1:0",
            document_id="doc1",
            document_name="uploaded.pdf",
            chunk_index=0,
            chunk_text=(
                "The study evaluated patients with suspected colorectal lesions and reported "
                "that optical diagnosis was compared with histopathology as the reference standard."
            ),
            retrieval_score=1.0,
            mode="attached_document",
        ),
        ContextItem(
            citation_id="DOC2",
            chunk_id="doc1:1",
            document_id="doc1",
            document_name="uploaded.pdf",
            chunk_index=1,
            chunk_text=(
                "Main limitations included single-center recruitment and the need for external "
                "validation before routine clinical deployment."
            ),
            retrieval_score=1.0,
            mode="attached_document",
        ),
    ]
    return ContextBundle(
        mode="attached_document",
        query="Summarize case",
        expanded_queries=[],
        items=items,
        context_text="\n".join(f"[{item.citation_id}] {item.chunk_text}" for item in items),
        reasoning_steps=[
            {
                "step": 1,
                "title": "Document grounding",
                "description": "Loaded 2 passages from the attached document.",
                "status": "done",
            }
        ],
        retrieval_method="attachment",
        total_candidates=2,
        retrieval_latency_ms=0.0,
        context_policy={},
    )


def _llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        provider="test",
        model_used="deterministic",
        token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )


def test_stream_mode_defaults_to_safe():
    settings = Settings(**_safe_settings_kwargs())
    assert settings.stream_mode == "safe"


def test_unsafe_stream_mode_is_rejected():
    with pytest.raises(ValueError, match="Unsafe pre-validation streaming"):
        Settings(**_safe_settings_kwargs(), stream_mode="fast")


@pytest.mark.asyncio
async def test_no_answer_token_before_validation_completes(monkeypatch):
    release_generation = asyncio.Event()
    events: asyncio.Queue[dict | None] = asyncio.Queue()

    async def fake_build_bundle(*_args, **_kwargs):
        return _bundle()

    async def fake_generate(*_args, **_kwargs):
        await release_generation.wait()
        return _llm_response("Amlodipine 5 mg daily was prescribed [SRC1]. [CONFIDENCE: 0.95]")

    monkeypatch.setattr(rag_service, "build_retrieval_bundle", fake_build_bundle)
    monkeypatch.setattr(llm_service, "generate_with_metadata", fake_generate)
    monkeypatch.setattr(rag_service._settings, "stream_mode", "safe")

    async def collect():
        async for event in rag_service.query_stream("What medication was prescribed?"):
            await events.put(event)
        await events.put(None)

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.05)

    queued = []
    while not events.empty():
        queued.append(events.get_nowait())
    assert not any(event and event["type"] == "token" for event in queued)

    release_generation.set()
    await task
    queued.extend([event async for event in _drain_queue(events)])
    tokens = [event["content"] for event in queued if event and event["type"] == "token"]
    assert "".join(tokens).startswith("Amlodipine")


async def _drain_queue(queue: asyncio.Queue):
    while not queue.empty():
        yield queue.get_nowait()


@pytest.mark.asyncio
async def test_citation_failure_abstains_without_leaking_draft(monkeypatch):
    unsafe_draft = "Amlodipine was definitely prescribed. [CONFIDENCE: 0.95]"
    calls = 0

    async def fake_build_bundle(*_args, **_kwargs):
        return _bundle()

    async def fake_generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _llm_response(unsafe_draft)

    monkeypatch.setattr(rag_service, "build_retrieval_bundle", fake_build_bundle)
    monkeypatch.setattr(llm_service, "generate_with_metadata", fake_generate)
    monkeypatch.setattr(rag_service._settings, "stream_mode", "safe")

    tokens = []
    trace = {}
    async for event in rag_service.query_stream("What medication was prescribed?"):
        if event["type"] == "token":
            tokens.append(event["content"])
        elif event["type"] == "trace":
            trace = event["trace"]

    answer = "".join(tokens)
    assert calls == 2
    assert "definitely prescribed" not in answer
    assert "not have enough evidence" in answer
    assert trace["guardrails"]["failed_citation_grounding"] is True


@pytest.mark.asyncio
async def test_internal_query_wrapper_uses_safe_answer(monkeypatch):
    async def fake_build_bundle(*_args, **_kwargs):
        return _bundle()

    async def fake_generate(*_args, **_kwargs):
        return _llm_response("Uncited unsafe draft. [CONFIDENCE: 0.95]")

    monkeypatch.setattr(rag_service, "build_retrieval_bundle", fake_build_bundle)
    monkeypatch.setattr(llm_service, "generate_with_metadata", fake_generate)

    result = await rag_service.query("What medication was prescribed?")
    assert "Uncited unsafe draft" not in result["answer"]
    assert result["model_used"] == "guardrail:failed-citation-grounding"
    assert result["trace"]["guardrails"]["failed_citation_grounding"] is True


@pytest.mark.asyncio
async def test_attached_document_summary_has_cited_extractive_fallback(monkeypatch):
    calls = 0

    async def fake_generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _llm_response(
            "I do not have enough evidence in the provided documents to answer this safely."
        )

    monkeypatch.setattr(llm_service, "generate_with_metadata", fake_generate)
    monkeypatch.setattr(rag_service._settings, "llm_provider", "gemini")

    result = await rag_service.generate_answer(
        question="Summarize case",
        bundle=_attached_document_bundle(),
    )

    assert calls == 2
    assert "Attached Document Summary" in result.answer
    assert "I do not have enough evidence" not in result.answer
    assert "[DOC1]" in result.answer
    assert "[DOC2]" in result.answer
    assert result.citations
    assert result.model_used == "guardrail:attached-document-extractive-summary"
    assert result.trace["guardrails"]["attached_document_extractive_fallback"] is True


@pytest.mark.asyncio
async def test_attached_document_summary_formats_cited_paragraph(monkeypatch):
    async def fake_generate(*_args, **_kwargs):
        return _llm_response(
            "The study evaluated patients with suspected colorectal lesions [DOC1]. "
            "Optical diagnosis was compared with histopathology as the reference standard [DOC1]. "
            "Limitations included single-center recruitment and need for external validation [DOC2]. "
            "[EVIDENCE_SUPPORT: 0.90]"
        )

    monkeypatch.setattr(llm_service, "generate_with_metadata", fake_generate)
    monkeypatch.setattr(rag_service._settings, "llm_provider", "gemini")

    result = await rag_service.generate_answer(
        question="Summarize case",
        bundle=_attached_document_bundle(),
    )

    assert result.model_used == "test:deterministic"
    assert "## Summary" in result.answer
    assert "## Key Points" in result.answer
    assert "| Topic | Finding | Source |" in result.answer
    assert "[DOC1]" in result.answer
    assert "[DOC2]" in result.answer
    assert result.citations


def test_chat_state_machine_rejects_invalid_transition():
    machine = ChatStateMachine()
    with pytest.raises(RuntimeError):
        machine.transition(ChatState.READY_TO_STREAM)


@pytest.mark.asyncio
async def test_agent_synthesis_draft_is_not_emitted(monkeypatch):
    orchestrator = AgentOrchestrator()
    monkeypatch.setattr(orchestrator, "_create_step", lambda **_kwargs: asyncio.sleep(0, result=str(uuid.uuid4())))
    monkeypatch.setattr(orchestrator, "_update_workflow", lambda *_args, **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(orchestrator, "_update_step", lambda *_args, **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(llm_service, "generate", lambda *_args, **_kwargs: asyncio.sleep(0, result="unsafe draft"))

    state = {
        "query": "question",
        "workflow_type": "general",
        "image_id": None,
        "session_id": None,
        "user_id": "user-1",
        "patient_id": None,
        "plan": [],
        "current_step": 0,
        "tool_results": [],
        "synthesis": "",
        "verification_passed": None,
        "final_answer": "",
        "events": [],
        "error": None,
        "workflow_id": str(uuid.uuid4()),
        "failure_code": None,
    }

    result = await orchestrator.synthesize_node(state)
    emitted = result["events"]
    assert not any(event.get("type") == "answer_drafted" for event in emitted)
    assert not any(event.get("type") == "synthesis" and event.get("content") for event in emitted)


@pytest.mark.asyncio
async def test_rest_chat_uses_chat_orchestrator(monkeypatch):
    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    called = {}

    async def fake_user():
        return User(id="user-1", email="u@example.com", name="U", role="physician", created_at="now")

    async def fake_db():
        yield SimpleNamespace()

    async def fake_stream(db, request, user):
        called["message"] = request.message
        called["user_id"] = user.id
        yield {"type": "done", "session_id": "s1", "message_id": "m1"}

    app.dependency_overrides[require_authenticated_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    monkeypatch.setattr(chat.chat_orchestrator, "stream", fake_stream)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert called == {"message": "hello", "user_id": "user-1"}


def _chat_ws_app() -> FastAPI:
    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    return app


def _create_chat_session(session_id: uuid.UUID, user_id: str) -> None:
    async def create():
        async with async_session_factory() as session:
            session.add(ChatSession(id=session_id, user_id=user_id, title="Safe stream"))
            await session.commit()

    asyncio.run(create())


def _issue_ws_ticket(client: TestClient, token: str, session_id: uuid.UUID) -> str:
    response = client.post(
        "/api/auth/ws-ticket",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": str(session_id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "websocket_ticket"
    return payload["ticket"]


def test_websocket_rejects_unauthenticated():
    client = TestClient(_chat_ws_app())
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/chat/ws/{uuid.uuid4()}"):
            pass
    assert exc.value.code == 1008


def test_websocket_rejects_other_users_session(user_token):
    session_id = uuid.uuid4()
    _create_chat_session(session_id, "demo-admin-001")
    client = TestClient(_chat_ws_app())
    response = client.post(
        "/api/auth/ws-ticket",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"session_id": str(session_id)},
    )
    assert response.status_code == 404


def test_websocket_ticket_requires_session_id(admin_token):
    client = TestClient(_chat_ws_app())
    response = client.post(
        "/api/auth/ws-ticket",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )
    assert response.status_code == 422


def test_websocket_ticket_bound_to_exact_session(admin_token):
    session_a = uuid.uuid4()
    session_b = uuid.uuid4()
    _create_chat_session(session_a, "demo-admin-001")
    _create_chat_session(session_b, "demo-admin-001")

    client = TestClient(_chat_ws_app())
    ticket = _issue_ws_ticket(client, admin_token, session_a)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/chat/ws/{session_b}?ticket={ticket}"):
            pass
    assert exc.value.code == 1008


def test_websocket_uses_chat_orchestrator(monkeypatch, admin_token):
    session_id = uuid.uuid4()
    _create_chat_session(session_id, "demo-admin-001")
    called = {}

    async def no_rate_limit(_request):
        return None

    async def fake_stream(db, request, user):
        called["session_id"] = request.session_id
        called["message"] = request.message
        called["user_id"] = user.id
        yield {"type": "done", "session_id": str(request.session_id), "message_id": "m1"}

    monkeypatch.setattr(chat.rate_limiter, "check", no_rate_limit)
    monkeypatch.setattr(chat.chat_orchestrator, "stream", fake_stream)

    client = TestClient(_chat_ws_app())
    ticket = _issue_ws_ticket(client, admin_token, session_id)
    with client.websocket_connect(f"/api/chat/ws/{session_id}?ticket={ticket}") as websocket:
        websocket.send_json({"message": "hello"})
        event = websocket.receive_json()

    assert event["type"] == "done"
    assert called == {"session_id": session_id, "message": "hello", "user_id": "demo-admin-001"}


def test_websocket_ticket_is_single_use(monkeypatch, admin_token):
    session_id = uuid.uuid4()
    _create_chat_session(session_id, "demo-admin-001")

    async def no_rate_limit(_request):
        return None

    async def fake_stream(db, request, user):
        yield {"type": "done", "session_id": str(request.session_id), "message_id": "m1"}

    monkeypatch.setattr(chat.rate_limiter, "check", no_rate_limit)
    monkeypatch.setattr(chat.chat_orchestrator, "stream", fake_stream)

    client = TestClient(_chat_ws_app())
    ticket = _issue_ws_ticket(client, admin_token, session_id)
    with client.websocket_connect(f"/api/chat/ws/{session_id}?ticket={ticket}") as websocket:
        websocket.send_json({"message": "hello"})
        assert websocket.receive_json()["type"] == "done"

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/chat/ws/{session_id}?ticket={ticket}"):
            pass
    assert exc.value.code == 1008


def test_websocket_rejects_access_token_query(admin_token):
    session_id = uuid.uuid4()
    _create_chat_session(session_id, "demo-admin-001")
    client = TestClient(_chat_ws_app())

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/chat/ws/{session_id}?access_token={admin_token}"):
            pass
    assert exc.value.code == 1008


def test_websocket_rejects_malformed_ticket():
    session_id = uuid.uuid4()
    _create_chat_session(session_id, "demo-admin-001")
    client = TestClient(_chat_ws_app())

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/chat/ws/{session_id}?ticket=malformed"):
            pass
    assert exc.value.code == 1008


def test_websocket_rejects_expired_ticket(monkeypatch, admin_token):
    from app.services.websocket_ticket import websocket_ticket_service

    session_id = uuid.uuid4()
    _create_chat_session(session_id, "demo-admin-001")
    client = TestClient(_chat_ws_app())
    ticket = _issue_ws_ticket(client, admin_token, session_id)
    original_now = websocket_ticket_service._now_epoch
    monkeypatch.setattr(websocket_ticket_service, "_now_epoch", lambda: original_now() + 120)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/chat/ws/{session_id}?ticket={ticket}"):
            pass
    assert exc.value.code == 1008


def test_websocket_ticket_raw_value_not_logged(caplog, admin_token):
    session_id = uuid.uuid4()
    _create_chat_session(session_id, "demo-admin-001")
    client = TestClient(_chat_ws_app())

    ticket = _issue_ws_ticket(client, admin_token, session_id)

    assert ticket not in caplog.text
