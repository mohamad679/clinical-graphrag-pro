"""
Phase 0 security and configuration tests.
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.core.auth import User
from app.core.config import get_settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _set_base_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "phase0-test-secret-0123456789abcdef")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app_user:strong-password@postgres:5432/clinical_graphrag")
    monkeypatch.setenv("REDIS_URL", "rediss://:strong-password@redis:6379/0")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    get_settings.cache_clear()


def test_settings_reject_short_jwt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "short")
    monkeypatch.setenv("DEBUG", "false")
    get_settings.cache_clear()

    with pytest.raises(ValueError):
        get_settings()


@pytest.mark.anyio
async def test_graph_visualize_uses_temporal_backend_when_neo4j_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("USE_NEO4J", "false")
    get_settings.cache_clear()
    from app.api import graph

    app = FastAPI()
    app.include_router(graph.router, prefix="/api")
    app.dependency_overrides[graph.graph_reader] = lambda: User(
        id="demo-physician-001",
        email="physician@clinicalgraph.ai",
        name="Dr. Physician",
        role="physician",
        created_at="2026-03-26T00:00:00+00:00",
        session_id="graph-test-session",
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/graph/visualize")

    assert response.status_code == 200
    assert response.json()["source"] == "temporal_graph"


@pytest.mark.anyio
async def test_graph_seed_disabled_in_production(monkeypatch: pytest.MonkeyPatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OBSERVABILITY_MODE", "PRODUCTION_METADATA_ONLY")
    get_settings.cache_clear()
    from app.api import graph

    app = FastAPI()
    app.include_router(graph.router, prefix="/api")
    app.dependency_overrides[graph.graph_admin] = lambda: User(
        id="demo-admin-001",
        email="admin@clinicalgraph.ai",
        name="Dr. Admin",
        role="admin",
        created_at="2026-03-26T00:00:00+00:00",
        session_id="graph-admin-session",
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/graph/seed", json={"patient_id": "Patient_A"})

    assert response.status_code == 404


@pytest.mark.anyio
async def test_fine_tune_disabled_returns_503(monkeypatch: pytest.MonkeyPatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_FINE_TUNE", "false")
    get_settings.cache_clear()
    from app.api import fine_tune

    app = FastAPI()
    app.include_router(fine_tune.router, prefix="/api")
    app.dependency_overrides[fine_tune.require_admin] = lambda: User(
        id="demo-admin-001",
        email="admin@clinicalgraph.ai",
        name="Dr. Admin",
        role="admin",
        created_at="2026-03-26T00:00:00+00:00",
        session_id="fine-tune-admin-session",
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/fine-tune/datasets")

    assert response.status_code == 503
    assert response.json() == {"detail": "Fine-tuning is disabled in this deployment"}
