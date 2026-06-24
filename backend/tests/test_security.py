"""
Security-focused regression tests.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException
import os

os.environ.setdefault("ENABLE_DEMO_AUTH", "true")
os.environ.setdefault("JWT_SECRET", "test-secret-for-ci-0123456789abcdef")

from app.api import admin
from app.api.images import _resolve_safe_upload_file
from app.core.auth import auth_service


app_under_test = FastAPI()
app_under_test.include_router(admin.router, prefix="/api")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app_under_test)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_token() -> str:
    result = auth_service.authenticate("user@clinicalgraph.ai", "user123")
    assert result is not None
    return result[1]


@pytest.mark.anyio
async def test_admin_health_requires_auth(client):
    response = await client.get("/api/admin/health")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_admin_health_requires_admin_role(client, user_token):
    response = await client.get(
        "/api/admin/health",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


def test_resolve_safe_upload_file_rejects_path_traversal(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    with pytest.raises(HTTPException) as exc_info:
        _resolve_safe_upload_file(uploads, "..")
    assert exc_info.value.status_code == 400


def test_resolve_safe_upload_file_accepts_normal_filename(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    resolved = _resolve_safe_upload_file(uploads, "test.png")
    assert resolved == (uploads / "test.png").resolve()
