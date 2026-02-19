"""
Unit tests for the Clinical GraphRAG Pro API.
Run with: pytest tests/ -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Root & Health ────────────────────────────────────────


@pytest.mark.anyio
async def test_root(client):
    """Root endpoint returns app info."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert data["docs"] == "/docs"


@pytest.mark.anyio
async def test_health(client):
    """Health endpoint returns status."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "dependencies" in data


# ── Documents API ────────────────────────────────────────


@pytest.mark.anyio
async def test_list_documents_empty(client):
    """List documents returns empty list initially."""
    response = await client.get("/api/documents")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert "total" in data


@pytest.mark.anyio
async def test_upload_invalid_type(client):
    """Uploading an unsupported file type returns 400."""
    response = await client.post(
        "/api/documents/upload",
        files={"file": ("test.exe", b"fake content", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


# ── Chat API ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_chat_sync(client):
    """Sync chat endpoint returns a response."""
    response = await client.post(
        "/api/chat/sync",
        json={"message": "What is hypertension?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data


@pytest.mark.anyio
async def test_chat_empty_message(client):
    """Empty message is rejected by validation."""
    response = await client.post("/api/chat/sync", json={"message": ""})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_list_sessions(client):
    """List sessions endpoint works."""
    response = await client.get("/api/chat/sessions")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ── Graph API ────────────────────────────────────────────


@pytest.mark.anyio
async def test_graph_stats(client):
    """Graph stats endpoint returns stats."""
    response = await client.get("/api/graph/stats")
    assert response.status_code == 200
    data = response.json()
    assert "vector_store" in data
    assert "knowledge_graph" in data


@pytest.mark.anyio
async def test_graph_search_empty(client):
    """Graph search without query returns help message."""
    response = await client.get("/api/graph/search")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
