"""
Unit tests for the Clinical GraphRAG Pro Agent API and tools.
Run with: pytest tests/test_agents.py -v
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import agents
from app.core.auth import User, require_authenticated_user
from app.core.database import get_db
from app.services.tool_registry import tool_registry


class _FakeExecuteResult:
    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None


class _FakeDB:
    async def execute(self, *_args, **_kwargs):
        return _FakeExecuteResult()


# ── Tool Registry Tests ──────────────────────────────────


@pytest.mark.asyncio
async def test_medical_calculator_bmi():
    """Test BMI calculation."""
    result = await tool_registry.execute(
        "medical_calculator",
        {"calculator": "bmi", "params": {"weight_kg": 70, "height_m": 1.75}},
    )
    assert result["value"] == 22.9
    assert result["category"] == "Normal"


@pytest.mark.asyncio
async def test_medical_calculator_egfr():
    """Test eGFR calculation (CKD-EPI)."""
    result = await tool_registry.execute(
        "medical_calculator",
        {"calculator": "egfr", "params": {"creatinine": 1.0, "age": 50, "gender": "male"}},
    )
    assert "value" in result
    assert result["value"] > 90


@pytest.mark.asyncio
async def test_tool_not_found():
    """Test execution of non-existent tool."""
    result = await tool_registry.execute("fake_tool", {})
    assert "error" in result


@pytest.mark.asyncio
async def test_search_documents_tool_applies_user_scope(monkeypatch):
    from app.services import tool_registry as tool_registry_module
    from app.services import query_engine as query_engine_module

    captured: dict[str, object] = {}

    def fake_search(query: str, top_k: int = 5, filters: dict | None = None):
        captured["query"] = query
        captured["top_k"] = top_k
        captured["filters"] = filters
        return []

    async def fake_bm25_stats():
        return {"total_documents": 1, "active_documents": 1, "index_loaded": True}

    monkeypatch.setattr(tool_registry_module.vector_store_service, "search", fake_search)
    monkeypatch.setattr(query_engine_module.bm25_index, "get_stats_async", fake_bm25_stats)
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "use_query_expansion", False)
    monkeypatch.setattr(get_settings(), "use_hybrid_search", False)


    result = await tool_registry.execute(
        "search_documents",
        {"query": "hypertension", "top_k": 3, "user_id": "user-123", "tenant_id": "tenant-123"},
    )
    assert "error" in result
    assert result["results"] == []
    assert captured == {
        "query": "hypertension",
        "top_k": 9,
        "filters": {"tenant_id": "tenant-123", "user_id": "user-123"},
    }



# ── Agent API Tests ──────────────────────────────────────


@pytest.fixture
async def client():
    """Async HTTP client for testing agent endpoints without full app import."""
    app = FastAPI()
    app.include_router(agents.router, prefix="/api")

    async def _fake_get_db():
        yield _FakeDB()

    async def _fake_user():
        return User(
            id="user-123",
            email="clinician@example.com",
            name="Clinician",
            role="physician",
            created_at="2026-03-26T00:00:00+00:00",
            session_id="session-123",
        )

    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[require_authenticated_user] = _fake_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_list_tools(client):
    response = await client.get("/api/agents/tools")
    assert response.status_code == 200
    tools = response.json()
    assert len(tools) >= 5
    names = [t["name"] for t in tools]
    assert "search_documents" in names
    assert "medical_calculator" in names


@pytest.mark.anyio
async def test_list_workflows_empty(client):
    response = await client.get("/api/agents/workflows")
    assert response.status_code == 200
    data = response.json()
    assert "workflows" in data
    assert isinstance(data["workflows"], list)


@pytest.mark.anyio
async def test_run_workflow_validation(client):
    response = await client.post("/api/agents/run", json={})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_run_workflow_start(client, monkeypatch):
    async def _fake_run(**_kwargs):
        yield {"type": "reasoning", "step": 1, "title": "Plan", "description": "Mock run"}

    monkeypatch.setattr(agents.agent_orchestrator, "run", _fake_run)

    async with client.stream(
        "POST",
        "/api/agents/run",
        json={"query": "Calculate BMI for 70kg 1.75m"},
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line:
                assert line.startswith("data:")
                break
