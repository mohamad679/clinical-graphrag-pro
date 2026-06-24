from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import User, get_current_user
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.rate_limiter import RateLimiter
from app.core.retrieval_scope import RetrievalScope
from app.models.evaluation import EvaluationRun
from app.models.medical_image import MedicalImage
from app.services.bm25_index import BM25Index
from app.services.query_engine import QueryEngine


def _user(user_id: str, role: str = "physician", tenant_id: str | None = None) -> User:
    return User(
        id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
        role=role,
        tenant_id=tenant_id or user_id,
        created_at="2026-06-05T00:00:00+00:00",
        is_verified=True,
    )


@pytest.mark.anyio
async def test_retrieval_scope_collision_does_not_alias_user_and_tenant(monkeypatch):
    bm25 = BM25Index(use_database=False)
    bm25.add_document(
        [{"chunk_id": "allowed", "text": "ordinary diabetes note"}],
        "doc-allowed",
        "allowed.txt",
        user_id="user-123",
    )
    bm25._metadata[-1]["tenant_id"] = "tenant-A"
    bm25.add_document(
        [{"chunk_id": "blocked", "text": "collision-only renal secret"}],
        "doc-blocked",
        "blocked.txt",
        user_id="other-user",
    )
    bm25._metadata[-1]["tenant_id"] = "user-123"

    async def no_expand(*args, **kwargs):
        return ""

    monkeypatch.setattr("app.services.query_engine.bm25_index", bm25)
    monkeypatch.setattr("app.services.query_engine.llm_service.generate", no_expand)

    result = await QueryEngine().query(
        "collision-only",
        mode="sparse",
        scope=RetrievalScope(tenant_id="tenant-A", principal_user_id="user-123"),
    )
    assert result.results == []


@pytest.mark.anyio
async def test_image_file_access_requires_authorized_image_id(tmp_path):
    from app.api import images

    image_path = tmp_path / "owned.png"
    image_path.write_bytes(b"image-bytes")
    thumb_path = tmp_path / "owned.webp"
    thumb_path.write_bytes(b"thumb-bytes")
    image_id = uuid4()

    async with async_session_factory() as session:
        session.add(
            MedicalImage(
                id=image_id,
                user_id="physician-a",
                tenant_id="tenant-a",
                filename="unguessable.png",
                original_filename="xray.png",
                file_path=str(image_path),
                thumbnail_path=str(thumb_path),
                file_size=len(b"image-bytes"),
                mime_type="image/png",
                analysis_status="uploaded",
            )
        )
        await session.commit()

    app = FastAPI()
    app.include_router(images.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: _user("physician-a", tenant_id="tenant-a")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.get(f"/api/images/{image_id}/file")
        assert ok.status_code == 200
        assert ok.content == b"image-bytes"

        thumb = await client.get(f"/api/images/{image_id}/thumbnail")
        assert thumb.status_code == 200
        assert thumb.content == b"thumb-bytes"

        guessed = await client.get("/api/images/files/unguessable.png")
        assert guessed.status_code == 404

    app.dependency_overrides[get_current_user] = lambda: _user("physician-b", tenant_id="tenant-b")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        wrong_tenant = await client.get(f"/api/images/{image_id}/file")
        assert wrong_tenant.status_code == 404


@pytest.mark.anyio
async def test_eval_history_is_tenant_and_user_scoped():
    from app.api import eval as eval_api

    async with async_session_factory() as session:
        session.add_all(
            [
                EvaluationRun(
                    evaluation_type=eval_api.SINGLE_RESPONSE_EVAL_TYPE,
                    tenant_id="tenant-a",
                    user_id="physician-a",
                    dataset_size=1,
                    metrics={"overall_score": 0.9},
                    metadata_={"query": "a", "answer": "a"},
                ),
                EvaluationRun(
                    evaluation_type=eval_api.SINGLE_RESPONSE_EVAL_TYPE,
                    tenant_id="tenant-b",
                    user_id="physician-b",
                    dataset_size=1,
                    metrics={"overall_score": 0.1},
                    metadata_={"query": "b", "answer": "b"},
                ),
            ]
        )
        await session.commit()

    app = FastAPI()
    app.include_router(eval_api.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: _user("physician-a", tenant_id="tenant-a")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/eval/history")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["evaluations"][0]["query"] == "a"

        forbidden = await client.get("/api/eval/history?include_global=true")
        assert forbidden.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: _user("admin-a", role="admin", tenant_id="tenant-a")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        global_response = await client.get("/api/eval/history?include_global=true")
        assert global_response.status_code == 200
        assert global_response.json()["total"] == 2


@pytest.mark.anyio
async def test_fine_tune_requires_admin_and_enabled_flag():
    from app.api import fine_tune

    settings = get_settings()
    original = settings.enable_fine_tune
    settings.enable_fine_tune = False
    app = FastAPI()
    app.include_router(fine_tune.router, prefix="/api")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauth = await client.get("/api/fine-tune/datasets")
        assert unauth.status_code == 401

    app.dependency_overrides[get_current_user] = lambda: _user("physician-a", tenant_id="tenant-a")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        non_admin = await client.get("/api/fine-tune/datasets")
        assert non_admin.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: _user("admin-a", role="admin", tenant_id="tenant-a")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        disabled = await client.get("/api/fine-tune/datasets")
        assert disabled.status_code == 503
    settings.enable_fine_tune = original


@pytest.mark.anyio
async def test_rate_limiter_ignores_spoofed_forwarded_for():
    settings = get_settings()
    settings.rate_limit_trust_forwarded_for = False
    request = SimpleNamespace(
        state=SimpleNamespace(),
        headers={"X-Forwarded-For": "203.0.113.10"},
        client=SimpleNamespace(host="10.0.0.5"),
    )
    assert RateLimiter()._get_identifier(request) == "ip:10.0.0.5"


@pytest.mark.anyio
async def test_rate_limiter_atomic_window_and_fail_closed(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.lock = asyncio.Lock()
            self.count = 0

        async def eval(self, *_args):
            async with self.lock:
                if self.count >= 2:
                    return [0, 0]
                self.count += 1
                return [1, 2 - self.count]

    fake = FakeRedis()

    async def fake_client():
        return fake

    monkeypatch.setattr("app.core.rate_limiter.get_redis_client", fake_client)
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    results = await asyncio.gather(*(limiter.is_allowed("same-user") for _ in range(4)))
    assert [allowed for allowed, _ in results].count(True) == 2
    assert [allowed for allowed, _ in results].count(False) == 2

    async def broken_client():
        raise RuntimeError("redis down")

    settings = get_settings()
    original = settings.rate_limit_redis_failure_policy
    settings.rate_limit_redis_failure_policy = "fail_closed"
    monkeypatch.setattr("app.core.rate_limiter.get_redis_client", broken_client)
    assert await limiter.is_allowed("expensive") == (False, 0)
    settings.rate_limit_redis_failure_policy = original
