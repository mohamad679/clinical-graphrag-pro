import asyncio
import os

import pytest
import redis.asyncio as aioredis

from app.core.caching import CacheManager, make_cache_key, make_cache_prefix
from app.core.config import get_settings
from app.core.redis import redis_service


@pytest.fixture
def phase1_env():
    return None


async def _redis_available(url: str) -> bool:
    client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
        return True
    except Exception:
        return False
    finally:
        await client.aclose()


@pytest.fixture
async def real_redis(monkeypatch):
    settings = get_settings()
    candidates = [
        value
        for value in (os.environ.get("REDIS_URL"), settings.redis_url, "redis://localhost:6379/0")
        if value
    ]
    redis_url = None
    for candidate in candidates:
        if await _redis_available(candidate):
            redis_url = candidate
            break
    if redis_url is None:
        pytest.skip("Redis service is not available for distributed cache integration test.")

    monkeypatch.setattr(settings, "redis_url", redis_url)
    monkeypatch.setattr(settings, "cache_enabled", True)
    monkeypatch.setattr(settings, "cache_backend", "redis")
    monkeypatch.setattr(settings, "cache_ttl", 2)
    await redis_service.close()
    await redis_service.connect()
    await CacheManager.invalidate_prefix_async("cgrag:test-cache:")
    yield redis_url
    await CacheManager.invalidate_prefix_async("cgrag:test-cache:")
    await redis_service.close()


@pytest.mark.asyncio
async def test_redis_cache_is_distributed_across_clients(real_redis):
    key = make_cache_key("test-cache", "patient-a", "tenant-a", {"query": "distributed"})
    await CacheManager.set_async(key, {"value": "from-cache-a"}, ttl_seconds=30)

    client_b = aioredis.from_url(real_redis, encoding="utf-8", decode_responses=True)
    try:
        raw_value = await client_b.get(key)
    finally:
        await client_b.aclose()

    assert raw_value is not None
    assert await CacheManager.get_async(key) == {"value": "from-cache-a"}


@pytest.mark.asyncio
async def test_redis_cache_ttl_namespace_and_invalidation(real_redis):
    tenant_a_key = make_cache_key("test-cache", "patient-a", "tenant-a", {"query": "same"})
    tenant_b_key = make_cache_key("test-cache", "patient-a", "tenant-b", {"query": "same"})
    assert tenant_a_key != tenant_b_key

    await CacheManager.set_async(tenant_a_key, {"tenant": "a"}, ttl_seconds=1)
    await CacheManager.set_async(tenant_b_key, {"tenant": "b"}, ttl_seconds=30)

    assert await CacheManager.get_async(tenant_a_key) == {"tenant": "a"}
    assert await CacheManager.get_async(tenant_b_key) == {"tenant": "b"}

    await asyncio.sleep(1.2)
    assert await CacheManager.get_async(tenant_a_key) is None
    assert await CacheManager.get_async(tenant_b_key) == {"tenant": "b"}

    deleted = await CacheManager.invalidate_prefix_async(
        make_cache_prefix("test-cache", tenant_id="tenant-b", patient_id="patient-a")
    )
    assert deleted >= 1
    assert await CacheManager.get_async(tenant_b_key) is None


@pytest.mark.asyncio
async def test_redis_outage_policy_and_memory_backend(monkeypatch, phase1_env):
    settings = get_settings()
    monkeypatch.setattr(settings, "cache_enabled", True)
    monkeypatch.setattr(settings, "cache_backend", "redis")
    monkeypatch.setattr(settings, "app_env", "production")
    await redis_service.close()

    key = make_cache_key("test-cache", "patient-a", "tenant-a", {"query": "outage"})
    await CacheManager.set_async(key, {"value": "not-stored"}, ttl_seconds=30)
    assert await CacheManager.get_async(key) is None

    monkeypatch.setattr(settings, "app_env", "development")
    await CacheManager.set_async(key, {"value": "memory-fallback"}, ttl_seconds=30)
    assert await CacheManager.get_async(key) == {"value": "memory-fallback"}

    monkeypatch.setattr(settings, "cache_backend", "in-memory")
    memory_key = make_cache_key("test-cache", "patient-a", "tenant-a", {"query": "memory"})
    await CacheManager.set_async(memory_key, {"value": "local"}, ttl_seconds=30)
    assert await CacheManager.get_async(memory_key) == {"value": "local"}
