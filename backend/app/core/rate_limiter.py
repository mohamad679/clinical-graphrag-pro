"""
Redis-backed sliding window rate limiter.
"""

import logging
import secrets
import time
from ipaddress import ip_address, ip_network
from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import get_settings
from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)

SLIDING_WINDOW_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1])
local current = redis.call('ZCARD', KEYS[1])
if current >= tonumber(ARGV[3]) then
  return {0, 0}
end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return {1, tonumber(ARGV[3]) - current - 1}
"""


class RateLimiter:
    """Redis-backed sliding window rate limiter."""

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60,
        prefix: str = "rl",
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.prefix = prefix

    async def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """
        Returns (allowed, remaining_requests).
        Uses Redis ZSET sliding window.
        """
        try:
            redis = await get_redis_client()
            now = time.time()
            window_start = now - self.window_seconds
            key = f"{self.prefix}:{identifier}"
            member = f"{now}:{secrets.token_hex(8)}"

            result = await redis.eval(
                SLIDING_WINDOW_LUA,
                1,
                key,
                window_start,
                now,
                self.max_requests,
                member,
                self.window_seconds * 2,
            )
            return bool(int(result[0])), int(result[1])

        except Exception as exc:
            settings = get_settings()
            fail_closed = settings.rate_limit_redis_failure_policy == "fail_closed"
            logger.warning(
                "Rate limiter Redis error (%s): %s",
                "fail-closed" if fail_closed else "fail-open",
                exc,
            )
            return (False, 0) if fail_closed else (True, self.max_requests)

    async def check(self, request) -> None:
        """FastAPI dependency. Raises 429 if rate limit exceeded."""
        identifier = self._get_identifier(request)
        settings = get_settings()
        original_policy = settings.rate_limit_redis_failure_policy
        fail_closed_paths = list(settings.rate_limit_fail_closed_paths or [])
        path_fail_closed = any(str(request.url.path).startswith(prefix) for prefix in fail_closed_paths)
        if path_fail_closed:
            settings.rate_limit_redis_failure_policy = "fail_closed"
        try:
            allowed, remaining = await self.is_allowed(identifier)
        finally:
            settings.rate_limit_redis_failure_policy = original_policy
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again later.",
                headers={"Retry-After": str(self.window_seconds)},
            )

    def _get_identifier(self, request) -> str:
        """Use JWT user_id if authenticated, else IP."""
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}"
        user = getattr(request.state, "user", None)
        if getattr(user, "id", None):
            return f"user:{user.id}"
        return f"ip:{self._get_client_ip(request)}"

    def _get_client_ip(self, request) -> str:
        settings = get_settings()
        direct_ip = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded and settings.rate_limit_trust_forwarded_for and self._is_trusted_proxy(direct_ip):
            return forwarded.split(",")[0].strip() or direct_ip
        return direct_ip

    def _is_trusted_proxy(self, direct_ip: str) -> bool:
        settings = get_settings()
        try:
            parsed_ip = ip_address(direct_ip)
        except ValueError:
            return False
        for entry in settings.rate_limit_trusted_proxies or []:
            try:
                if parsed_ip in ip_network(str(entry), strict=False):
                    return True
            except ValueError:
                continue
        return False

    def get_stats(self) -> dict:
        """Retrieve rate limiter status."""
        settings = get_settings()
        return {
            "enabled": settings.rate_limit_enabled,
            "max_requests_per_minute": self.max_requests,
            "window_seconds": self.window_seconds,
            "prefix": self.prefix,
            "trust_forwarded_for": settings.rate_limit_trust_forwarded_for,
            "trusted_proxies": list(settings.rate_limit_trusted_proxies or []),
            "redis_failure_policy": settings.rate_limit_redis_failure_policy,
        }


# Module-level singleton
settings = get_settings()
rate_limiter = RateLimiter(
    max_requests=settings.rate_limit_per_minute,
    window_seconds=60,
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip health checks
        if request.url.path.endswith("/health"):
            return await call_next(request)

        settings = get_settings()
        if not settings.rate_limit_enabled:
            return await call_next(request)

        try:
            await rate_limiter.check(request)
        except HTTPException as exc:
            logger.warning(f"Rate limit exceeded: {exc.detail}")
            return Response(
                content=f'{{"detail":"{exc.detail}"}}',
                status_code=exc.status_code,
                media_type="application/json",
                headers=exc.headers,
            )

        response = await call_next(request)
        return response
