"""
Token-Bucket Rate Limiter.
Per-IP request limiting with configurable thresholds.
"""

import logging
import time
from dataclasses import dataclass, field

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """Token bucket for a single client."""
    tokens: float
    max_tokens: float
    refill_rate: float  # tokens per second
    last_refill: float = field(default_factory=time.monotonic)

    def consume(self) -> bool:
        """Try to consume a token. Returns True if allowed."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    @property
    def retry_after(self) -> float:
        """Seconds until a token is available."""
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.refill_rate


class RateLimiterService:
    """
    In-memory token-bucket rate limiter.
    In production, replace with Redis-backed limiter for multi-instance.
    """

    def __init__(self):
        settings = get_settings()
        self._buckets: dict[str, TokenBucket] = {}
        self._max_requests = settings.rate_limit_per_minute
        self._enabled = settings.rate_limit_enabled
        self._cleanup_interval = 300  # cleanup stale buckets every 5 min
        self._last_cleanup = time.monotonic()

    def check(self, client_ip: str) -> tuple[bool, float]:
        """
        Check if request is allowed for this IP.
        Returns (allowed, retry_after_seconds).
        """
        if not self._enabled:
            return True, 0.0

        self._maybe_cleanup()

        if client_ip not in self._buckets:
            self._buckets[client_ip] = TokenBucket(
                tokens=float(self._max_requests),
                max_tokens=float(self._max_requests),
                refill_rate=self._max_requests / 60.0,
            )

        bucket = self._buckets[client_ip]
        allowed = bucket.consume()
        return allowed, bucket.retry_after

    def get_stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "max_requests_per_minute": self._max_requests,
            "active_buckets": len(self._buckets),
        }

    def _maybe_cleanup(self):
        """Remove stale buckets periodically."""
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        stale = [
            ip for ip, b in self._buckets.items()
            if now - b.last_refill > 600  # 10 min idle
        ]
        for ip in stale:
            del self._buckets[ip]


# Module-level singleton
rate_limiter = RateLimiterService()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = request.client.host if request.client else "unknown"

        # Skip health checks
        if request.url.path.endswith("/health"):
            return await call_next(request)

        allowed, retry_after = rate_limiter.check(client_ip)

        if not allowed:
            logger.warning(f"Rate limit exceeded for {client_ip}")
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

        response = await call_next(request)
        return response
