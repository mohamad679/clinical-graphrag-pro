"""
Redis client service — caching, session store, and pub/sub.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.metrics import observe_redis_operation
from app.core.observability import export_trace_context, trace_operation

logger = logging.getLogger(__name__)
settings = get_settings()


class RedisService:
    """Async Redis client wrapper."""

    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self):
        """Initialize Redis connection."""
        started = time.perf_counter()
        try:
            with trace_operation("redis.connect", component="redis", logger_=logger, command="PING"):
                self._client = aioredis.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=20,
                )
                client = self._client
                if client is None:
                    raise ConnectionError("Redis client was not initialized.")
                await client.ping()
            observe_redis_operation(time.perf_counter() - started, command="PING", success=True)
            logger.info("✅ Redis connected")
        except Exception as e:
            observe_redis_operation(time.perf_counter() - started, command="PING", success=False)
            logger.warning(f"⚠️  Redis unavailable: {e}  — caching disabled")
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def is_connected(self) -> bool:
        """Compatibility helper for cache callers."""
        return self.available

    async def get(self, key: str) -> Any | None:
        """Get a cached value (returns None if Redis is down)."""
        if not self._client:
            return None
        started = time.perf_counter()
        try:
            with trace_operation("redis.get", component="redis", logger_=logger, command="GET", redis_key=key):
                value = await self._client.get(key)
            observe_redis_operation(time.perf_counter() - started, command="GET", success=True)
            return json.loads(value) if value else None
        except Exception as e:
            observe_redis_operation(time.perf_counter() - started, command="GET", success=False)
            logger.debug(f"Redis GET failed: {e}")
            return None

    async def set(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        """Set a cached value with optional TTL in seconds."""
        if not self._client:
            return False
        started = time.perf_counter()
        try:
            serialized = json.dumps(value, default=str)
            with trace_operation(
                "redis.set",
                component="redis",
                logger_=logger,
                command="SET",
                redis_key=key,
                ttl_seconds=ttl or settings.cache_ttl,
            ):
                await self._client.set(key, serialized, ex=ttl or settings.cache_ttl)
            observe_redis_operation(time.perf_counter() - started, command="SET", success=True)
            return True
        except Exception as e:
            observe_redis_operation(time.perf_counter() - started, command="SET", success=False)
            logger.debug(f"Redis SET failed: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a cached key."""
        if not self._client:
            return False
        started = time.perf_counter()
        try:
            with trace_operation("redis.delete", component="redis", logger_=logger, command="DEL", redis_key=key):
                await self._client.delete(key)
            observe_redis_operation(time.perf_counter() - started, command="DEL", success=True)
            return True
        except Exception as e:
            observe_redis_operation(time.perf_counter() - started, command="DEL", success=False)
            logger.debug(f"Redis DELETE failed: {e}")
            return False

    async def delete_prefix(self, prefix: str) -> int:
        """Delete all keys with the given prefix using SCAN."""
        if not self._client:
            return 0
        started = time.perf_counter()
        deleted = 0
        try:
            with trace_operation("redis.delete_prefix", component="redis", logger_=logger, command="SCAN_DEL"):
                async for key in self._client.scan_iter(match=f"{prefix}*"):
                    deleted += int(await self._client.delete(key))
            observe_redis_operation(time.perf_counter() - started, command="SCAN_DEL", success=True)
            return deleted
        except Exception as e:
            observe_redis_operation(time.perf_counter() - started, command="SCAN_DEL", success=False)
            logger.debug(f"Redis prefix DELETE failed: {e}")
            return 0

    async def health_check(self) -> dict:
        """Check Redis connectivity."""
        if not self._client:
            return {"status": "disconnected"}
        started = time.perf_counter()
        try:
            with trace_operation("redis.health_check", component="redis", logger_=logger, command="PING"):
                await self._client.ping()
                info = await self._client.info("memory")
            observe_redis_operation(time.perf_counter() - started, command="PING", success=True)
            return {
                "status": "healthy",
                "used_memory_human": info.get("used_memory_human", "unknown"),
            }
        except Exception as e:
            observe_redis_operation(time.perf_counter() - started, command="PING", success=False)
            return {"status": "unhealthy", "error": str(e)}

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Redis connection closed", extra={**export_trace_context(), "component": "redis"})


# Module-level singleton
redis_service = RedisService()


async def get_redis_client() -> aioredis.Redis:
    """Return the active Redis client connection."""
    if not redis_service._client:
        raise ConnectionError("Redis client is not connected.")
    return redis_service._client
