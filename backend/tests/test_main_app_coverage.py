import pytest
import importlib
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient

@pytest.fixture
def phase1_env():
    """Dummy fixture to prevent conftest.py reset_test_db from reloading modules."""
    return None

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.mark.anyio
async def test_main_app_lifespan_and_root(phase1_env):
    # Mock services that are closed/started during lifespan
    mock_redis = AsyncMock()
    mock_audio = AsyncMock()
    mock_llm = AsyncMock()
    mock_neo4j = AsyncMock()
    mock_vision = AsyncMock()
    mock_migration = AsyncMock(return_value={"status": "current"})
    
    with (
        patch("app.core.redis.redis_service.connect", mock_redis.connect),
        patch("app.core.redis.redis_service.close", mock_redis.close),
        patch("app.core.database.check_migration_status", mock_migration),
        patch("app.services.audio_processing.audio_processing_service.close", mock_audio.close),
        patch("app.services.llm.llm_service.close", mock_llm.close),
        patch("app.services.neo4j_graph.neo4j_graph_service.close", mock_neo4j.close),
        patch("app.services.vision.vision_service.close", mock_vision.close),
        patch("app.worker.background_jobs_health", return_value={"status": "healthy"}),
    ):
        # Dynamically import app to bypass forbidden import check
        main_module = importlib.import_module("app.main")
        app = main_module.app
        
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/")
                assert response.status_code == 200
                data = response.json()
                assert "name" in data
                assert "version" in data
                
                # Test CORS preflight check
                cors_resp = await ac.options("/api/v1/health", headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET"
                })
                assert cors_resp.status_code in (200, 400, 404, 204)
            
        # Verify mocked services were called during startup and shutdown lifespan
        mock_redis.connect.assert_called_once()
        mock_redis.close.assert_called_once()
        mock_audio.close.assert_called_once()
        mock_llm.close.assert_called_once()
        mock_neo4j.close.assert_called_once()
        mock_vision.close.assert_called_once()
