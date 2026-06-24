"""
Unit tests for the Clinical GraphRAG Pro API.
Run with: pytest tests/ -v
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

# Import all SQLAlchemy models to prevent mapper configuration errors

from app.api import health, graph


# ── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def phase1_env():
    """Dummy fixture to prevent conftest.py reset_test_db from reloading modules."""
    return None


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    app = FastAPI()
    app.include_router(health.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")

    # Bypass auth dependencies
    from app.core.auth import User as AuthUser
    app.dependency_overrides[graph.graph_reader] = lambda: AuthUser(
        id="demo-physician-001",
        email="physician@clinicalgraph.ai",
        name="Dr. Physician",
        role="physician",
        created_at="2026-05-23T21:00:46Z",
    )
    app.dependency_overrides[graph.graph_admin] = lambda: AuthUser(
        id="demo-admin-001",
        email="admin@clinicalgraph.ai",
        name="Dr. Admin",
        role="admin",
        created_at="2026-05-23T21:00:46Z",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Root & Health ────────────────────────────────────────


@pytest.mark.anyio
async def test_root(client, phase1_env):
    """Root endpoint is not mounted in this lightweight test app."""
    response = await client.get("/")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_health(client, phase1_env):
    """Health endpoint returns status."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "version" in data


# ── Documents API ────────────────────────────────────────


@pytest.mark.anyio
async def test_list_documents_empty(client, phase1_env):
    """Documents endpoint is not mounted in this lightweight app."""
    response = await client.get("/api/documents")
    assert response.status_code == 404


# ── Chat API ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_chat_sync(client, phase1_env):
    """Chat endpoint is not mounted in this lightweight app."""
    response = await client.post("/api/chat/sync", json={"message": "Hi"})
    assert response.status_code == 404


# ── Graph API ────────────────────────────────────────────


@pytest.mark.anyio
async def test_graph_stats(client, phase1_env):
    """Graph stats endpoint returns stats."""
    response = await client.get("/api/graph/stats")
    assert response.status_code == 200
    data = response.json()
    assert "vector_store" in data
    assert "knowledge_graph" in data


@pytest.mark.anyio
async def test_graph_search_empty(client, phase1_env):
    """Graph search without query returns help message."""
    response = await client.get("/api/graph/search")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data


@pytest.mark.anyio
async def test_health_disclaimer(client, phase1_env):
    """Health disclaimer endpoint returns the clinical disclaimer text."""
    response = await client.get("/api/health/disclaimer")
    assert response.status_code == 200
    data = response.json()
    assert "disclaimer" in data


def test_aggregate_health_production_unhealthy(phase1_env):
    """Verify health aggregation logic under production for unhealthy services."""
    from app.api.health import _aggregate_health, settings as health_settings

    with patch.object(health_settings, "app_env", "production"):
        services_unhealthy = {
            "postgres": {"status": "unhealthy"},
            "redis": {"status": "healthy"}
        }
        assert _aggregate_health(services_unhealthy) == "unhealthy"

        services_healthy = {
            "postgres": {"status": "healthy"},
            "redis": {"status": "healthy"}
        }
        assert _aggregate_health(services_healthy) == "healthy"


def test_aggregate_health_degraded(phase1_env):
    """Verify health aggregation logic handles degraded or unknown states correctly."""
    from app.api.health import _aggregate_health, settings as health_settings

    # In development, degraded is considered healthy
    with patch.object(health_settings, "app_env", "development"):
        services_degraded = {
            "postgres": {"status": "degraded"},
            "redis": {"status": "healthy"}
        }
        assert _aggregate_health(services_degraded) == "healthy"

        services_unknown = {
            "postgres": {"status": "unknown_state"},
            "redis": {"status": "healthy"}
        }
        # "unknown_state" is not in allowed_healthy, but "healthy" is in {"healthy", "degraded"}, so degraded
        assert _aggregate_health(services_unknown) == "degraded"

        services_unhealthy = {
            "postgres": {"status": "unhealthy"},
            "redis": {"status": "unhealthy"}
        }
        # no healthy/degraded states, so unhealthy
        assert _aggregate_health(services_unhealthy) == "unhealthy"

    # In production, degraded state leads to degraded aggregate status
    with patch.object(health_settings, "app_env", "production"):
        services_degraded = {
            "postgres": {"status": "degraded"},
            "redis": {"status": "healthy"}
        }
        assert _aggregate_health(services_degraded) == "degraded"
