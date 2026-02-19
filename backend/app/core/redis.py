"""
Redis client service — caching, session store, and pub/sub.
"""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RedisService:
    """Async Redis client wrapper."""

    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self):
        """Initialize Redis connection."""
        try:
            self._client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,
            )
            await self._client.ping()
            logger.info("✅ Redis connected")
        except Exception as e:
            logger.warning(f"⚠️  Redis unavailable: {e}  — caching disabled")
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    async def get(self, key: str) -> Any | None:
        """Get a cached value (returns None if Redis is down)."""
        if not self._client:
            return None
        try:
            value = await self._client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.debug(f"Redis GET failed: {e}")
            return None

    async def set(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        """Set a cached value with optional TTL in seconds."""
        if not self._client:
            return False
        try:
            serialized = json.dumps(value, default=str)
            await self._client.set(key, serialized, ex=ttl or settings.cache_ttl)
            return True
        except Exception as e:
            logger.debug(f"Redis SET failed: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a cached key."""
        if not self._client:
            return False
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.debug(f"Redis DELETE failed: {e}")
            return False

    async def health_check(self) -> dict:
        """Check Redis connectivity."""
        if not self._client:
            return {"status": "disconnected"}
        try:
            await self._client.ping()
            info = await self._client.info("memory")
            return {
                "status": "healthy",
                "used_memory_human": info.get("used_memory_human", "unknown"),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            logger.info("Redis connection closed")


# Module-level singleton
redis_service = RedisService()
