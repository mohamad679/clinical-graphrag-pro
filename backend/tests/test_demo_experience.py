import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch, AsyncMock

from app.api import graph
from app.core.auth import User as AuthUser

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def mock_temporal_graph_service():
    with patch("app.api.graph.temporal_graph_service") as mock:
        yield mock

@pytest.fixture
def create_client(mock_temporal_graph_service):
    def _create_client(user_role: str, user_id: str):
        app = FastAPI()
        app.include_router(graph.router, prefix="/api")
        
        # Override auth dependency
        user = AuthUser(
            id=user_id,
            email=f"{user_role}@clinicalgraph.ai",
            name=f"Dr. {user_role.capitalize()}",
            role=user_role,
            created_at="2026-05-23T21:00:46Z",
        )
        app.dependency_overrides[graph.graph_reader] = lambda: user
        app.dependency_overrides[graph.graph_admin] = lambda: user
        
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")
    return _create_client

@pytest.mark.anyio
async def test_graph_visualize_admin_global_scope(create_client, mock_temporal_graph_service):
    """Verify that an admin user can fetch visualization without tenant scoping."""
    client = create_client(user_role="admin", user_id="admin-001")
    
    mock_temporal_graph_service.export_for_visualization = AsyncMock(return_value={"nodes": [], "links": []})
    
    async with client as cl:
        response = await cl.get("/api/graph/visualize?patient_id=pat-100")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "links" in data
        
        # Verify that tenant_id passed to service is None for admin
        mock_temporal_graph_service.export_for_visualization.assert_called_once_with(
            limit=100,
            tenant_id=None,
            patient_id="pat-100"
        )

@pytest.mark.anyio
async def test_graph_visualize_physician_tenant_isolation(create_client, mock_temporal_graph_service):
    """Verify that a physician user has their tenant_id automatically appended to visualizer scope."""
    client = create_client(user_role="physician", user_id="physician-tenant-123")
    
    mock_temporal_graph_service.export_for_visualization = AsyncMock(return_value={"nodes": [], "links": []})
    
    async with client as cl:
        response = await cl.get("/api/graph/visualize?patient_id=pat-200&limit=50")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        
        # Verify that tenant_id passed to service is physician's user_id
        mock_temporal_graph_service.export_for_visualization.assert_called_once_with(
            limit=50,
            tenant_id="physician-tenant-123",
            patient_id="pat-200"
        )
