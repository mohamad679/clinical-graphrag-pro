"""
Integration tests — end-to-end workflows.
Tests cross-service flows without external dependencies.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.datasets import DatasetService
from app.services.fine_tune import FineTuneService, TrainingConfig
from app.services.model_registry import ModelRegistry


# ── Fixtures ────────────────────────────────────────────

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Auth → Protected Resources Flow ────────────────────

class TestAuthFlow:
    """Test complete authentication workflow."""

    @pytest.mark.anyio
    async def test_full_auth_flow(self, client):
        # 1. Login
        login = await client.post("/api/auth/login", json={
            "email": "admin@clinicalgraph.ai",
            "password": "admin123",
        })
        assert login.status_code == 200
        token = login.json()["token"]

        # 2. Access protected resource with token
        me = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200
        assert me.json()["authenticated"] is True

        # 3. Access health (public)
        health = await client.get("/api/admin/health")
        assert health.status_code == 200

        # 4. Check session recorded
        sessions = await client.get("/api/admin/sessions")
        assert sessions.status_code == 200
        assert len(sessions.json()["sessions"]) > 0


# ── Fine-Tune Pipeline Flow ────────────────────────────

class TestFineTunePipeline:
    """Test dataset → train → register → deploy flow."""

    @pytest.mark.asyncio
    async def test_full_finetune_pipeline(self):
        # 1. Create dataset
        ds = DatasetService()
        dataset = ds.create_dataset("Pipeline Test", "Integration test", "alpaca")
        assert dataset is not None

        # 2. Validate dataset
        validation = ds.validate(dataset.id)
        assert "valid" in validation

        # 3. Create and run training job
        ft = FineTuneService()
        config = TrainingConfig(
            dataset_id=dataset.id,
            num_epochs=1,
            learning_rate=2e-4,
        )
        job = ft.create_job(config, adapter_name="pipeline-test-adapter")
        completed = await ft.start_training(job.id, num_samples=5)
        assert completed.status.value == "completed"

        # 4. Register model
        reg = ModelRegistry()
        model = reg.register(
            name="pipeline-test-model",
            base_model="llama-3.1-8b",
            dataset_name=dataset.name,
            training_loss=completed.final_loss,
        )
        assert model.id is not None

        # 5. Deploy model
        assert reg.deploy(model.id) is True
        active = reg.get_active_model()
        assert active is not None

        # 6. Undeploy
        assert reg.undeploy(model.id) is True


# ── Non-DB Endpoint Smoke Tests ─────────────────────────

class TestNonDBEndpoints:
    """Smoke test endpoints that don't require PostgreSQL."""

    @pytest.mark.anyio
    async def test_core_endpoints_accessible(self, client):
        """All major non-DB endpoints respond without 5xx errors."""
        endpoints = [
            ("GET", "/"),
            ("GET", "/api/health"),
            ("GET", "/api/graph/stats"),
            ("GET", "/api/agents/tools"),
            ("GET", "/api/eval/history"),
            ("GET", "/api/fine-tune/datasets"),
            ("GET", "/api/fine-tune/jobs"),
            ("GET", "/api/fine-tune/models"),
            ("GET", "/api/admin/health"),
            ("GET", "/api/admin/metrics"),
            ("GET", "/api/admin/sessions"),
            ("GET", "/api/admin/config"),
            ("GET", "/api/auth/me"),
        ]

        for method, path in endpoints:
            response = await client.request(method, path)
            assert response.status_code < 500, f"{method} {path} returned {response.status_code}"
