"""
Tenant-scoped cache abstraction.

Redis mode is a real distributed async cache. If Redis is unavailable, the
policy is explicit: development/offline-demo mode falls back to local memory;
production bypasses cache rather than using per-process memory.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from app.core.config import get_settings
from app.core.metrics import (
    observe_cache_operation,
    record_cache_backend_error,
    record_cache_fallback,
)
from app.core.redis import redis_service

logger = logging.getLogger(__name__)
settings = get_settings()

_in_memory_cache: dict[str, tuple[str, float]] = {}


def make_cache_key(
    namespace: str,
    patient_id: str | None,
    tenant_id: str | None,
    payload: Any,
    **kwargs: Any,
) -> str:
    """Construct a deterministic tenant/patient-scoped cache key."""
    if namespace in {"retrieval", "rerank", "llm"}:
        if not tenant_id or not patient_id:
            raise ValueError(
                f"Security violation: cache namespace '{namespace}' requires active patient and tenant context parameters."
            )

    serialized_payload = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    serialized_kwargs = json.dumps(kwargs, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(f"{serialized_payload}|{serialized_kwargs}".encode("utf-8")).hexdigest()
    return f"cgrag:{namespace}:{tenant_id or 'global'}:{patient_id or 'global'}:{digest}"


def make_cache_prefix(namespace: str, *, tenant_id: str | None = None, patient_id: str | None = None) -> str:
    """Construct a prefix for scoped invalidation."""
    return f"cgrag:{namespace}:{tenant_id or 'global'}:{patient_id or 'global'}:"


class CacheManager:
    """Cache manager with async Redis and sync compatibility wrappers."""

    @staticmethod
    def _fallback_allowed() -> bool:
        current = get_settings()
        return bool(current.offline_demo_mode or current.app_env == "development")

    @staticmethod
    def _backend_name() -> str:
        return str(get_settings().cache_backend or "in-memory").strip().lower()

    @staticmethod
    def _run_sync(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        record_cache_fallback(from_backend="redis", to_backend="bypass_active_event_loop")
        return None

    @staticmethod
    def _memory_get(key: str) -> Any | None:
        entry = _in_memory_cache.get(key)
        if not entry:
            return None
        value_text, expires_at = entry
        if time.time() >= expires_at:
            _in_memory_cache.pop(key, None)
            return None
        return json.loads(value_text)

    @staticmethod
    def _memory_set(key: str, value: Any, ttl_seconds: int) -> None:
        _in_memory_cache[key] = (json.dumps(value, default=str, separators=(",", ":")), time.time() + ttl_seconds)

    @staticmethod
    async def get_async(key: str) -> Any | None:
        """Fetch a value from Redis or the configured fallback."""
        if not get_settings().cache_enabled:
            return None
        backend = CacheManager._backend_name()
        started = time.perf_counter()
        if backend == "redis":
            if redis_service.is_connected():
                try:
                    value = await redis_service.get(key)
                    observe_cache_operation(
                        (time.perf_counter() - started) * 1000,
                        backend="redis",
                        operation="get",
                        outcome="hit" if value is not None else "miss",
                    )
                    return value
                except Exception:
                    record_cache_backend_error(backend="redis", operation="get")
                    logger.warning("Redis cache get failed; applying configured fallback", extra={"cache_key_prefix": key[:48]})
            if CacheManager._fallback_allowed():
                record_cache_fallback(from_backend="redis", to_backend="in-memory")
                value = CacheManager._memory_get(key)
                observe_cache_operation(
                    (time.perf_counter() - started) * 1000,
                    backend="in-memory",
                    operation="get",
                    outcome="hit" if value is not None else "miss",
                )
                return value
            record_cache_fallback(from_backend="redis", to_backend="bypass")
            return None

        value = CacheManager._memory_get(key)
        observe_cache_operation(
            (time.perf_counter() - started) * 1000,
            backend="in-memory",
            operation="get",
            outcome="hit" if value is not None else "miss",
        )
        return value

    @staticmethod
    async def set_async(key: str, value: Any, ttl_seconds: int | None = None, ttl: int | None = None) -> None:
        """Store a value with TTL. Values are JSON serialized."""
        if not get_settings().cache_enabled:
            return
        ttl_final = int(ttl_seconds or ttl or get_settings().cache_ttl)
        backend = CacheManager._backend_name()
        started = time.perf_counter()
        if backend == "redis":
            if redis_service.is_connected():
                try:
                    ok = await redis_service.set(key, value, ttl=ttl_final)
                    observe_cache_operation((time.perf_counter() - started) * 1000, backend="redis", operation="set", outcome="set")
                    if ok:
                        return
                    record_cache_backend_error(backend="redis", operation="set")
                except Exception:
                    record_cache_backend_error(backend="redis", operation="set")
                    logger.warning("Redis cache set failed; applying configured fallback", extra={"cache_key_prefix": key[:48]})
            if not CacheManager._fallback_allowed():
                record_cache_fallback(from_backend="redis", to_backend="bypass")
                return
            record_cache_fallback(from_backend="redis", to_backend="in-memory")

        CacheManager._memory_set(key, value, ttl_final)
        observe_cache_operation((time.perf_counter() - started) * 1000, backend="in-memory", operation="set", outcome="set")

    @staticmethod
    async def delete_async(key: str) -> None:
        """Delete a single cache key."""
        backend = CacheManager._backend_name()
        started = time.perf_counter()
        if backend == "redis" and redis_service.is_connected():
            try:
                await redis_service.delete(key)
                observe_cache_operation((time.perf_counter() - started) * 1000, backend="redis", operation="delete", outcome="delete")
            except Exception:
                record_cache_backend_error(backend="redis", operation="delete")
        _in_memory_cache.pop(key, None)
        if backend != "redis":
            observe_cache_operation((time.perf_counter() - started) * 1000, backend="in-memory", operation="delete", outcome="delete")

    @staticmethod
    async def invalidate_prefix_async(prefix: str) -> int:
        """Invalidate all keys beginning with prefix."""
        deleted = 0
        backend = CacheManager._backend_name()
        if backend == "redis" and redis_service.is_connected():
            try:
                deleted += await redis_service.delete_prefix(prefix)
            except Exception:
                record_cache_backend_error(backend="redis", operation="invalidate_prefix")
        for key in list(_in_memory_cache):
            if key.startswith(prefix):
                _in_memory_cache.pop(key, None)
                deleted += 1
        return deleted

    @staticmethod
    def get(key: str) -> Any | None:
        result = CacheManager._run_sync(CacheManager.get_async(key))
        if result is not None:
            return result
        if CacheManager._backend_name() == "redis" and CacheManager._fallback_allowed():
            return CacheManager._memory_get(key)
        return None

    @staticmethod
    def set(key: str, value: Any, ttl: int | None = None, ttl_seconds: int | None = None) -> None:
        result = CacheManager._run_sync(CacheManager.set_async(key, value, ttl_seconds=ttl_seconds, ttl=ttl))
        if result is None and (CacheManager._backend_name() != "redis" or CacheManager._fallback_allowed()):
            CacheManager._memory_set(key, value, int(ttl_seconds or ttl or get_settings().cache_ttl))

    @staticmethod
    def delete(key: str) -> None:
        result = CacheManager._run_sync(CacheManager.delete_async(key))
        if result is None:
            _in_memory_cache.pop(key, None)

    @staticmethod
    def invalidate_prefix(prefix: str) -> int:
        result = CacheManager._run_sync(CacheManager.invalidate_prefix_async(prefix))
        if isinstance(result, int):
            return result
        deleted = 0
        for key in list(_in_memory_cache):
            if key.startswith(prefix):
                _in_memory_cache.pop(key, None)
                deleted += 1
        return deleted

    @staticmethod
    def clear() -> None:
        """Clear only local in-memory cache entries."""
        _in_memory_cache.clear()
