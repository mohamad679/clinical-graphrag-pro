"""
Tests for Auth & Security (Phase 6).
JWT tokens, password hashing, rate limiting.
"""

import pytest
from sqlalchemy import select
from app.core.auth import AuthService, auth_service
from app.core.database import async_session_factory
from app.models.user import User as DBUser


# ── Password Hashing ────────────────────────────────────

class TestPasswordHashing:
    """Test password hashing utilities."""

    def test_hash_is_salted(self):
        h1 = AuthService._hash_password("test123")
        h2 = AuthService._hash_password("test123")
        assert h1 != h2
        assert h1.startswith("$argon2id$")
        assert h2.startswith("$argon2id$")

    def test_hash_different_passwords(self):
        h1 = AuthService._hash_password("password1")
        h2 = AuthService._hash_password("password2")
        assert h1 != h2

    def test_verify_correct(self):
        svc = AuthService()
        hashed = svc._hash_password("mypassword")
        assert svc._verify_password("mypassword", hashed) is True

    def test_verify_wrong(self):
        svc = AuthService()
        hashed = svc._hash_password("mypassword")
        assert svc._verify_password("wrongpassword", hashed) is False

    def test_verify_legacy_sha256_hash(self):
        svc = AuthService()
        legacy = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
        assert svc._verify_password("password", legacy) is True

    def test_pbkdf2_legacy_hash_requires_upgrade(self):
        svc = AuthService()
        legacy = svc._hash_password_pbkdf2_for_migration_tests("password")
        result = svc._verify_password_with_metadata("password", legacy)
        assert result.valid is True
        assert result.scheme == "pbkdf2_sha256"
        assert result.needs_rehash is True

    def test_sha256_legacy_hash_requires_upgrade(self):
        svc = AuthService()
        legacy = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
        result = svc._verify_password_with_metadata("password", legacy)
        assert result.valid is True
        assert result.scheme == "sha256_legacy"
        assert result.needs_rehash is True

    def test_malformed_hash_fails_safely(self):
        svc = AuthService()
        assert svc._verify_password("password", "pbkdf2_sha256$bad") is False
        assert svc._verify_password("password", "$argon2id$bad") is False


# ── JWT Tokens ──────────────────────────────────────────

class TestJWT:
    """Test JWT token creation and verification."""

    def test_create_token(self):
        result = auth_service.authenticate("admin@clinicalgraph.ai", "admin123")
        assert result is not None
        user, token = result
        assert len(token) > 50  # JWT tokens are long
        assert token.count(".") == 2  # Three parts

    def test_verify_valid_token(self):
        result = auth_service.authenticate("admin@clinicalgraph.ai", "admin123")
        assert result is not None
        _, token = result
        payload = auth_service.verify_token(token)
        assert payload["email"] == "admin@clinicalgraph.ai"
        assert payload["role"] == "admin"

    def test_verify_invalid_token(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_token("invalid.token.here")
        assert exc_info.value.status_code == 401

    def test_token_contains_claims(self):
        result = auth_service.authenticate("user@clinicalgraph.ai", "user123")
        assert result is not None
        _, token = result
        payload = auth_service.verify_token(token)
        assert "sub" in payload
        assert "sid" in payload
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload
        assert payload["role"] == "viewer"


# ── Authentication ──────────────────────────────────────

class TestAuthentication:
    """Test login flow."""

    def test_login_valid_admin(self):
        result = auth_service.authenticate("admin@clinicalgraph.ai", "admin123")
        assert result is not None
        user, _ = result
        assert user.role == "admin"

    def test_login_valid_user(self):
        result = auth_service.authenticate("user@clinicalgraph.ai", "user123")
        assert result is not None
        user, _ = result
        assert user.role == "viewer"

    def test_login_wrong_password(self):
        result = auth_service.authenticate("admin@clinicalgraph.ai", "wrongpass")
        assert result is None

    def test_login_nonexistent_user(self):
        result = auth_service.authenticate("nobody@example.com", "password")
        assert result is None

    def test_get_user_by_id(self):
        user = auth_service.get_user_by_id("demo-admin-001")
        assert user is not None
        assert user.email == "admin@clinicalgraph.ai"

    def test_get_user_not_found(self):
        user = auth_service.get_user_by_id("nonexistent-id")
        assert user is None

    @pytest.mark.asyncio
    async def test_legacy_pbkdf2_login_upgrades_persisted_hash(self):
        svc = AuthService()
        async with async_session_factory() as session:
            result = await session.execute(select(DBUser).where(DBUser.email == "user@clinicalgraph.ai"))
            db_user = result.scalar_one()
            db_user.password_hash = svc._hash_password_pbkdf2_for_migration_tests("user123")
            await session.commit()

        async with async_session_factory() as session:
            tokens = await svc.authenticate_async(session, "user@clinicalgraph.ai", "user123")
            await session.commit()
            assert tokens is not None

        async with async_session_factory() as session:
            result = await session.execute(select(DBUser).where(DBUser.email == "user@clinicalgraph.ai"))
            upgraded = result.scalar_one()
            assert upgraded.password_hash.startswith("$argon2id$")


# ── Sessions ────────────────────────────────────────────

class TestSessions:
    """Test session tracking."""

    def test_record_and_list(self):
        initial_count = len(auth_service.get_sessions())
        result = auth_service.authenticate("user@clinicalgraph.ai", "user123")
        assert result is not None
        assert len(auth_service.get_sessions()) == initial_count + 1
