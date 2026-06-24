from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import chat
from app.core.auth import User, require_authenticated_user
from app.core.config import Settings
from app.core.database import get_db


def _user(role: str = "physician") -> User:
    return User(
        id=f"{role}-1",
        email=f"{role}@example.test",
        name=role,
        role=role,
        tenant_id="tenant-1",
        created_at="2026-06-06T00:00:00+00:00",
        is_verified=True,
    )


def _chat_app(user: User) -> FastAPI:
    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    app.dependency_overrides[require_authenticated_user] = lambda: user

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    return app


def _production_settings_kwargs() -> dict:
    return {
        "app_env": "production",
        "debug": False,
        "jwt_secret": "prod-secret-for-test-0123456789abcdef",
        "database_url": "postgresql+asyncpg://app_user:strong-password@db.internal:5432/clinical",
        "redis_url": "rediss://:strong-password@redis.internal:6379/0",
        "cors_origins": ["https://clinical.example.test"],
        "google_api_key": "test-google-key",
        "observability_mode": "PRODUCTION_METADATA_ONLY",
        "_env_file": None,
    }


def test_unsafe_production_observability_mode_fails_startup_validation():
    with pytest.raises(ValueError, match="OBSERVABILITY_MODE must be PRODUCTION_METADATA_ONLY"):
        Settings(**{**_production_settings_kwargs(), "observability_mode": "LOCAL_SYNTHETIC_DEBUG"})


def test_safe_production_observability_mode_starts_and_disables_ticket_fallback():
    settings = Settings(**_production_settings_kwargs())
    assert settings.observability_mode == "PRODUCTION_METADATA_ONLY"
    assert settings.ws_ticket_allow_memory_fallback is False
    assert settings.internal_full_trace_enabled is False


@pytest.mark.anyio
async def test_debug_redacted_trace_unavailable_to_normal_user(monkeypatch):
    app = _chat_app(_user("physician"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat/sync?trace_level=debug_redacted", json={"message": "hello"})
    assert response.status_code == 403


@pytest.mark.anyio
async def test_debug_redacted_trace_available_to_admin_only_in_debug(monkeypatch):
    settings = chat.get_settings()
    original_debug = settings.debug
    original_env = settings.app_env
    settings.debug = True
    settings.app_env = "development"

    async def fake_execute_sync(db, request, user, *, trace_level="public", debug_trace_authorized=False):
        assert trace_level == "debug_redacted"
        assert debug_trace_authorized is True
        return {
            "answer": "ok",
            "sources": [],
            "citations": [],
            "reasoning_steps": [],
            "trace": {"trace_level": "debug_redacted", "final_context": {"redacted": True}},
            "error": False,
            "session_id": "s1",
            "message_id": "m1",
            "heuristic_evidence_support_score": 1.0,
            "confidence_score": 1.0,
            "confidence_score_deprecated": True,
            "model_used": "test",
            "clinician_review_required": True,
        }

    monkeypatch.setattr(chat.chat_orchestrator, "execute_sync", fake_execute_sync)
    try:
        app = _chat_app(_user("admin"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/chat/sync?trace_level=debug_redacted", json={"message": "hello"})
    finally:
        settings.debug = original_debug
        settings.app_env = original_env

    assert response.status_code == 200
    assert response.json()["trace"]["trace_level"] == "debug_redacted"


@pytest.mark.anyio
async def test_chat_sync_exception_returns_safe_error_envelope_and_request_id(monkeypatch, caplog):
    secret_exception = RuntimeError(
        "failed at /Users/alice/private/patient.txt token="
        "supersecret12345 "
        "postgresql://user:pass@db.internal/patient provider=https://llm.example/key"
    )

    async def explode(*_args, **_kwargs):
        raise secret_exception

    monkeypatch.setattr(chat.chat_orchestrator, "execute_sync", explode)
    app = _chat_app(_user("physician"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat/sync", json={"message": "hello"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"] == "retrieval_failed"
    assert payload["message"] == "Unable to complete the request safely."
    assert payload["request_id"]
    rendered = str(payload)
    assert "/Users/alice" not in rendered
    assert "supersecret12345" not in rendered
    assert "postgresql://user:pass" not in rendered
    assert "chat.sync_failed" in caplog.text
    assert "/Users/alice" not in caplog.text
    assert "supersecret12345" not in caplog.text
