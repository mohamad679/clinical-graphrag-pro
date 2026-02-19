"""
Tests for Auth & Security (Phase 6).
JWT tokens, password hashing, rate limiting.
"""

import pytest
import time
from app.core.auth import AuthService, auth_service
from app.core.rate_limiter import RateLimiterService, TokenBucket


# ── Password Hashing ────────────────────────────────────

class TestPasswordHashing:
    """Test password hashing utilities."""

    def test_hash_deterministic(self):
        h1 = AuthService._hash_password("test123")
        h2 = AuthService._hash_password("test123")
        assert h1 == h2

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
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload
        assert payload["role"] == "user"


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
        assert user.role == "user"

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


# ── Sessions ────────────────────────────────────────────

class TestSessions:
    """Test session tracking."""

    def test_record_and_list(self):
        from app.core.auth import User
        user = User(id="test", email="test@test.com", name="Test", role="user")
        initial_count = len(auth_service.get_sessions())
        auth_service.record_session(user, "test-jti-123")
        assert len(auth_service.get_sessions()) == initial_count + 1


# ── Rate Limiter ────────────────────────────────────────

class TestTokenBucket:
    """Test token bucket algorithm."""

    def test_consume_within_limit(self):
        bucket = TokenBucket(tokens=5.0, max_tokens=5.0, refill_rate=1.0)
        assert bucket.consume() is True
        assert bucket.consume() is True

    def test_consume_exhausted(self):
        bucket = TokenBucket(tokens=1.0, max_tokens=5.0, refill_rate=0.001)
        assert bucket.consume() is True
        assert bucket.consume() is False  # No tokens left

    def test_refill(self):
        bucket = TokenBucket(tokens=0.0, max_tokens=5.0, refill_rate=1000.0)
        # With high refill rate, tokens should replenish very quickly
        time.sleep(0.01)
        assert bucket.consume() is True

    def test_retry_after(self):
        bucket = TokenBucket(tokens=0.5, max_tokens=5.0, refill_rate=1.0)
        assert bucket.retry_after >= 0.0


class TestRateLimiter:
    """Test rate limiter service."""

    def test_check_allowed(self):
        limiter = RateLimiterService()
        allowed, _ = limiter.check("192.168.1.1")
        assert allowed is True

    def test_get_stats(self):
        limiter = RateLimiterService()
        stats = limiter.get_stats()
        assert "enabled" in stats
        assert "max_requests_per_minute" in stats
        assert "active_buckets" in stats
