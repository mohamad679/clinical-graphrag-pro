import pytest
from app.core.rate_limiter import RateLimiter
from app.core.redis import redis_service


@pytest.mark.anyio
async def test_rate_limiter_redis_blocks_after_limit():
    """After max_requests, the limiter should return is_allowed=False."""
    await redis_service.connect()
    if not redis_service.available:
        pytest.skip("Redis server is not available.")

    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        allowed, _ = await limiter.is_allowed("test-user")
        assert allowed
    allowed, remaining = await limiter.is_allowed("test-user")
    assert not allowed
    assert remaining == 0
