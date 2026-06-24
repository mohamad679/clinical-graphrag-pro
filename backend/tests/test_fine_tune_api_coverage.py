import inspect

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from app.core.auth import User, get_current_user
from app.api.fine_tune import router, require_fine_tune_enabled

@pytest.fixture
def phase1_env():
    return None

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def fine_tune_client():
    # Construct a FastAPI app with fine_tune.router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="admin-test",
        email="admin@example.test",
        name="Admin",
        role="admin",
        tenant_id="tenant-admin",
        created_at="2026-06-05T00:00:00+00:00",
        is_verified=True,
    )
    
    # Overrides/Dependency updates
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.mark.anyio
async def test_require_fine_tune_enabled_disabled():
    with patch("app.api.fine_tune.get_settings") as mock_settings:
        mock_settings.return_value.enable_fine_tune = False
        with pytest.raises(HTTPException) as exc:
            require_fine_tune_enabled()
        assert exc.value.status_code == 503

@pytest.mark.anyio
async def test_create_dataset_endpoint(fine_tune_client, phase1_env):
    mock_ds_service = AsyncMock()
    mock_ds_service.create_dataset_async.return_value = MagicMock(id="ds-123", name="My Dataset", created_at="2026-05-24T21:00:00Z")
    
    with (
        patch("app.api.fine_tune.get_settings") as mock_settings,
        patch("app.api.fine_tune._get_dataset_dependencies", return_value=(mock_ds_service, None))
    ):
        mock_settings.return_value.enable_fine_tune = True
        
        response = await fine_tune_client.post("/api/v1/fine-tune/datasets", json={
            "name": "My Dataset",
            "description": "desc",
            "template": "alpaca"
        })
        assert response.status_code == 200
        assert response.json()["id"] == "ds-123"

@pytest.mark.anyio
async def test_list_datasets_endpoint(fine_tune_client, phase1_env):
    mock_ds_service = AsyncMock()
    mock_ds_service.list_datasets_async.return_value = [{"id": "ds-123", "name": "Dataset"}]
    
    with (
        patch("app.api.fine_tune.get_settings") as mock_settings,
        patch("app.api.fine_tune._get_dataset_dependencies", return_value=(mock_ds_service, None))
    ):
        mock_settings.return_value.enable_fine_tune = True
        
        response = await fine_tune_client.get("/api/v1/fine-tune/datasets")
        assert response.status_code == 200
        assert len(response.json()["datasets"]) == 1

@pytest.mark.anyio
async def test_get_dataset_not_found(fine_tune_client, phase1_env):
    mock_ds_service = AsyncMock()
    mock_ds_service.get_dataset_async.return_value = None
    
    with (
        patch("app.api.fine_tune.get_settings") as mock_settings,
        patch("app.api.fine_tune._get_dataset_dependencies", return_value=(mock_ds_service, None))
    ):
        mock_settings.return_value.enable_fine_tune = True
        
        response = await fine_tune_client.get("/api/v1/fine-tune/datasets/fake")
        assert response.status_code == 404

@pytest.mark.anyio
async def test_add_sample_endpoint(fine_tune_client, phase1_env):
    mock_ds_service = AsyncMock()
    mock_ds_service.add_sample_async.return_value = True
    
    with (
        patch("app.api.fine_tune.get_settings") as mock_settings,
        patch("app.api.fine_tune._get_dataset_dependencies", return_value=(mock_ds_service, MagicMock))
    ):
        mock_settings.return_value.enable_fine_tune = True
        
        response = await fine_tune_client.post("/api/v1/fine-tune/datasets/ds-123/samples", json={
            "instruction": "Explain X",
            "input": "",
            "output": "X is..."
        })
        assert response.status_code == 200

@pytest.mark.anyio
async def test_generate_samples_endpoint(fine_tune_client, phase1_env):
    mock_ds_service = AsyncMock()
    mock_ds_service.generate_from_documents_async.return_value = 5
    
    with (
        patch("app.api.fine_tune.get_settings") as mock_settings,
        patch("app.api.fine_tune._get_dataset_dependencies", return_value=(mock_ds_service, None))
    ):
        mock_settings.return_value.enable_fine_tune = True
        
        response = await fine_tune_client.post("/api/v1/fine-tune/datasets/ds-123/generate", json={"num_pairs": 5})
        assert response.status_code == 200
        assert response.json()["generated"] == 5

@pytest.mark.anyio
async def test_start_training_endpoint(fine_tune_client, phase1_env):
    mock_ds_service = AsyncMock()
    mock_ds_service.get_dataset_async.return_value = MagicMock(sample_count=10)
    mock_ft_service = MagicMock()
    mock_ft_service.create_job_async = AsyncMock(return_value=MagicMock(id="job-123", adapter_name="my-adapter", status=MagicMock(value="pending")))
    mock_ft_service.validate_dataset.return_value = {"valid": True, "issues": []}
    mock_ft_service.mark_dispatched_async = AsyncMock()
    
    with (
        patch("app.api.fine_tune.get_settings") as mock_settings,
        patch("app.api.fine_tune._get_dataset_dependencies", return_value=(mock_ds_service, None)),
        patch("app.api.fine_tune._get_fine_tune_dependencies", return_value=(mock_ft_service, MagicMock)),
        patch("app.worker.dispatch_fine_tune_training", new=AsyncMock(return_value={"id": "worker-123", "transport": "celery"}))
    ):
        mock_settings.return_value.enable_fine_tune = True
        
        response = await fine_tune_client.post("/api/v1/fine-tune/start", json={
            "dataset_id": "ds-123"
        })
        assert response.status_code == 200
        assert response.json()["job_id"] == "job-123"
        assert response.json()["dispatch"]["transport"] == "celery"
        mock_ft_service.mark_dispatched_async.assert_awaited_once()


def test_fine_tune_api_does_not_start_training_with_create_task():
    import app.api.fine_tune as fine_tune_api

    source = inspect.getsource(fine_tune_api)
    assert "asyncio.create_task" not in source

@pytest.mark.anyio
async def test_cancel_job_endpoint(fine_tune_client, phase1_env):
    mock_ft_service = AsyncMock()
    mock_ft_service.cancel_job_async.return_value = True
    
    with (
        patch("app.api.fine_tune.get_settings") as mock_settings,
        patch("app.api.fine_tune._get_fine_tune_dependencies", return_value=(mock_ft_service, None))
    ):
        mock_settings.return_value.enable_fine_tune = True
        
        response = await fine_tune_client.post("/api/v1/fine-tune/jobs/job-123/cancel")
        assert response.status_code == 200
        assert response.json()["cancelled"] is True

@pytest.mark.anyio
async def test_model_registry_endpoints(fine_tune_client, phase1_env):
    mock_registry = AsyncMock()
    mock_registry.list_models_async.return_value = []
    mock_registry.register_async.return_value = MagicMock(id="m-123", name="My Model", version="1")
    mock_registry.deploy_async.return_value = True
    mock_registry.undeploy_async.return_value = True
    mock_registry.delete_model_async.return_value = True
    
    with (
        patch("app.api.fine_tune.get_settings") as mock_settings,
        patch("app.api.fine_tune._get_model_registry", return_value=mock_registry)
    ):
        mock_settings.return_value.enable_fine_tune = True
        
        # list
        resp = await fine_tune_client.get("/api/v1/fine-tune/models")
        assert resp.status_code == 200
        # register
        resp = await fine_tune_client.post("/api/v1/fine-tune/models", json={"name": "model", "base_model": "base"})
        assert resp.status_code == 200
        # deploy
        resp = await fine_tune_client.post("/api/v1/fine-tune/models/m-123/deploy")
        assert resp.status_code == 200
        # undeploy
        resp = await fine_tune_client.post("/api/v1/fine-tune/models/m-123/undeploy")
        assert resp.status_code == 200
        # delete
        resp = await fine_tune_client.delete("/api/v1/fine-tune/models/m-123")
        assert resp.status_code == 200
