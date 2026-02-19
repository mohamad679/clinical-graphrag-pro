"""
Shared test fixtures for Clinical GraphRAG Pro.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.auth import auth_service


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Unauthenticated async HTTP client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_client():
    """Authenticated async HTTP client (admin)."""
    result = auth_service.authenticate("admin@clinicalgraph.ai", "admin123")
    assert result is not None
    _, token = result

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac


@pytest.fixture
def admin_token() -> str:
    """Get an admin JWT token."""
    result = auth_service.authenticate("admin@clinicalgraph.ai", "admin123")
    assert result is not None
    return result[1]


@pytest.fixture
def user_token() -> str:
    """Get a regular user JWT token."""
    result = auth_service.authenticate("user@clinicalgraph.ai", "user123")
    assert result is not None
    return result[1]
