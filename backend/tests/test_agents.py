"""
Unit tests for the Clinical GraphRAG Pro Agent API and Tools.
Run with: pytest tests/test_agents.py -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.tool_registry import tool_registry

# ── Tool Registry Tests ──────────────────────────────────

@pytest.mark.asyncio
async def test_medical_calculator_bmi():
    """Test BMI calculation."""
    result = await tool_registry.execute(
        "medical_calculator",
        {"calculator": "bmi", "params": {"weight_kg": 70, "height_m": 1.75}}
    )
    assert result["value"] == 22.9
    assert result["category"] == "Normal"


@pytest.mark.asyncio
async def test_medical_calculator_egfr():
    """Test eGFR calculation (CKD-EPI)."""
    # Male, 50, Cr 1.0 -> should be around 100
    result = await tool_registry.execute(
        "medical_calculator",
        {"calculator": "egfr", "params": {"creatinine": 1.0, "age": 50, "gender": "male"}}
    )
    assert "value" in result
    assert result["value"] > 90  # Healthy kidney


@pytest.mark.asyncio
async def test_tool_not_found():
    """Test execution of non-existent tool."""
    result = await tool_registry.execute("fake_tool", {})
    assert "error" in result


# ── Agent API Tests ──────────────────────────────────────

@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_list_tools(client):
    """GET /agents/tools returns list of tools."""
    response = await client.get("/api/agents/tools")
    assert response.status_code == 200
    tools = response.json()
    assert len(tools) >= 5
    names = [t["name"] for t in tools]
    assert "search_documents" in names
    assert "medical_calculator" in names


@pytest.mark.anyio
async def test_list_workflows_empty(client):
    """GET /agents/workflows initially empty."""
    response = await client.get("/api/agents/workflows")
    assert response.status_code == 200
    data = response.json()
    assert "workflows" in data
    assert isinstance(data["workflows"], list)


@pytest.mark.anyio
async def test_run_workflow_validation(client):
    """POST /agents/run validates input."""
    response = await client.post("/api/agents/run", json={})
    assert response.status_code == 422  # Missing query


@pytest.mark.anyio
async def test_run_workflow_start(client):
    """POST /agents/run starts an SSE stream."""
    # We can't easily test the full stream without extensive mocking of LLM,
    # but we can check if it accepts the request and starts the stream.
    async with client.stream(
        "POST", 
        "/api/agents/run", 
        json={"query": "Calculate BMI for 70kg 1.75m"}
    ) as response:
        assert response.status_code == 200
        # Read first chunk
        async for line in response.aiter_lines():
            if line:
                assert line.startswith("data:")
                break
