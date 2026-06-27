"""
Shared test fixtures for Clinical GraphRAG Pro.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

TEST_DATABASE_PATH = Path(__file__).resolve().parents[1] / "test_auth_suite.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DATABASE_PATH}"

DEFAULT_TEST_ENV = {
    "DATABASE_URL": TEST_DATABASE_URL,
    "ENABLE_DEMO_AUTH": "false",
    "JWT_SECRET": "test-secret-for-ci-0123456789abcdef",
    "DEBUG": "false",
    "APP_ENV": "development",
}

for key, value in DEFAULT_TEST_ENV.items():
    os.environ.setdefault(key, value)


def _remove_test_database_files() -> None:
    for path in (
        TEST_DATABASE_PATH,
        TEST_DATABASE_PATH.with_name(TEST_DATABASE_PATH.name + "-wal"),
        TEST_DATABASE_PATH.with_name(TEST_DATABASE_PATH.name + "-shm"),
    ):
        if path.exists():
            path.unlink()


def _reload_default_test_modules() -> None:
    pass


async def _seed_users() -> None:
    _reload_default_test_modules()

    import app.models  # noqa: F401
    import app.models.evaluation  # noqa: F401
    from app.core.auth import AuthService
    from app.core.database import Base, async_session_factory, engine
    from app.models.user import User as DBUser

    await engine.dispose()
    _remove_test_database_files()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        session.add_all(
            [
                DBUser(
                    id="demo-admin-001",
                    email="admin@clinicalgraph.ai",
                    name="Dr. Admin",
                    role="admin",
                    password_hash=AuthService._hash_password("admin123"),
                    is_active=True,
                    is_verified=True,
                ),
                DBUser(
                    id="demo-physician-001",
                    email="physician@clinicalgraph.ai",
                    name="Dr. Physician",
                    role="physician",
                    password_hash=AuthService._hash_password("physician123"),
                    is_active=True,
                    is_verified=True,
                ),
                DBUser(
                    id="demo-nurse-001",
                    email="nurse@clinicalgraph.ai",
                    name="Nurse Reviewer",
                    role="nurse",
                    password_hash=AuthService._hash_password("nurse123"),
                    is_active=True,
                    is_verified=True,
                ),
                DBUser(
                    id="demo-viewer-001",
                    email="user@clinicalgraph.ai",
                    name="Clinical Viewer",
                    role="viewer",
                    password_hash=AuthService._hash_password("user123"),
                    is_active=True,
                    is_verified=True,
                ),
            ]
        )
        await session.commit()


@pytest.fixture(autouse=True)
def mock_embedding_model():
    """Globally mock the embedding model to avoid loading sentence-transformers under pytest."""
    import numpy as np
    from unittest.mock import MagicMock, patch

    from app.core.config import get_settings
    from app.services.vector_store import _EmbeddingChunkingMixin

    mock_embedder = MagicMock()
    mock_embedder.get_sentence_embedding_dimension.side_effect = (
        lambda: get_settings().embedding_dim
    )

    def mock_encode(texts, **kwargs):
        dim = get_settings().embedding_dim
        count = len(texts) if isinstance(texts, (list, tuple)) else 1
        embeddings = np.random.randn(count, dim).astype(np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / np.maximum(norms, 1e-12)

    mock_embedder.encode.side_effect = mock_encode

    with patch.object(_EmbeddingChunkingMixin, "_get_embedder", return_value=mock_embedder):
        yield


@pytest.fixture(autouse=True)
async def reset_test_db(request):
    if (
        "phase1_env" in request.fixturenames
        or "phase4_db" in request.fixturenames
        or request.path.name == "test_postgres_fts_migration.py"
    ):
        return

    await _seed_users()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Unauthenticated async HTTP client."""
    from fastapi import FastAPI

    from app.api import admin

    app = FastAPI()
    app.include_router(admin.router, prefix="/api")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_client():
    """Authenticated async HTTP client (admin)."""
    from fastapi import FastAPI

    from app.api import admin

    app = FastAPI()
    app.include_router(admin.router, prefix="/api")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post(
            "/api/auth/login",
            json={"email": "admin@clinicalgraph.ai", "password": "admin123"},
        )
        token = login.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


@pytest.fixture
def admin_token() -> str:
    from app.core.auth import auth_service

    result = auth_service.authenticate("admin@clinicalgraph.ai", "admin123")
    assert result is not None
    return result[1]


@pytest.fixture
def user_token() -> str:
    from app.core.auth import auth_service

    result = auth_service.authenticate("user@clinicalgraph.ai", "user123")
    assert result is not None
    return result[1]


@pytest.fixture
def nurse_token() -> str:
    from app.core.auth import auth_service

    result = auth_service.authenticate("nurse@clinicalgraph.ai", "nurse123")
    assert result is not None
    return result[1]


@pytest.fixture
def physician_token() -> str:
    from app.core.auth import auth_service

    result = auth_service.authenticate("physician@clinicalgraph.ai", "physician123")
    assert result is not None
    return result[1]
