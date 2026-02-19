"""
Tests for Admin API endpoints (Phase 6).
Login, health, metrics, sessions, config.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.logging_config import RequestMetrics


# ── Fixtures ────────────────────────────────────────────

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Login Endpoint ──────────────────────────────────────

class TestLoginAPI:

    @pytest.mark.anyio
    async def test_login_success(self, client):
        response = await client.post("/api/auth/login", json={
            "email": "admin@clinicalgraph.ai",
            "password": "admin123",
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "admin"

    @pytest.mark.anyio
    async def test_login_wrong_password(self, client):
        response = await client.post("/api/auth/login", json={
            "email": "admin@clinicalgraph.ai",
            "password": "wrongpassword",
        })
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_login_nonexistent_user(self, client):
        response = await client.post("/api/auth/login", json={
            "email": "nobody@example.com",
            "password": "password",
        })
        assert response.status_code == 401


# ── Auth Me Endpoint ────────────────────────────────────

class TestAuthMe:

    @pytest.mark.anyio
    async def test_me_unauthenticated(self, client):
        response = await client.get("/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False

    @pytest.mark.anyio
    async def test_me_authenticated(self, client):
        # First login
        login_resp = await client.post("/api/auth/login", json={
            "email": "admin@clinicalgraph.ai",
            "password": "admin123",
        })
        token = login_resp.json()["token"]

        # Then check /me
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["email"] == "admin@clinicalgraph.ai"


# ── Admin Health ────────────────────────────────────────

class TestAdminHealth:

    @pytest.mark.anyio
    async def test_health_returns_data(self, client):
        response = await client.get("/api/admin/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        assert "uptime_human" in data
        assert "services" in data
        assert "vector_store" in data["services"]
        assert "llm" in data["services"]
        assert "rate_limiter" in data["services"]


# ── Admin Metrics ───────────────────────────────────────

class TestAdminMetrics:

    @pytest.mark.anyio
    async def test_metrics_returns_data(self, client):
        response = await client.get("/api/admin/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total_requests" in data
        assert "total_errors" in data
        assert "error_rate_pct" in data
        assert "avg_latency_ms" in data
        assert "p95_latency_ms" in data


# ── Admin Sessions ──────────────────────────────────────

class TestAdminSessions:

    @pytest.mark.anyio
    async def test_sessions_returns_list(self, client):
        response = await client.get("/api/admin/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)


# ── Admin Config ────────────────────────────────────────

class TestAdminConfig:

    @pytest.mark.anyio
    async def test_config_returns_sections(self, client):
        response = await client.get("/api/admin/config")
        assert response.status_code == 200
        data = response.json()
        assert "llm" in data
        assert "embedding" in data
        assert "rag" in data
        assert "fine_tune" in data
        assert "rate_limit" in data


# ── Request Metrics Unit Tests ──────────────────────────

class TestRequestMetrics:

    def test_record_and_summary(self):
        metrics = RequestMetrics()
        metrics.record("/api/health", 200, 15.0)
        metrics.record("/api/chat/sync", 200, 250.0)
        metrics.record("/api/chat/sync", 500, 100.0)

        summary = metrics.get_summary()
        assert summary["total_requests"] == 3
        assert summary["total_errors"] == 1
        assert summary["error_rate_pct"] > 0
        assert summary["avg_latency_ms"] > 0

    def test_latency_cap(self):
        metrics = RequestMetrics()
        for i in range(1200):
            metrics.record("/test", 200, float(i))
        # Only last 1000 should be kept
        assert len(metrics.latencies) == 1000
