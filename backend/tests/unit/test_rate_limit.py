import uuid

import pytest

from app.core.rate_limit import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_sliding_window_limiter_caps_requests_per_key() -> None:
    limiter = SlidingWindowRateLimiter(count=2, window_seconds=60)
    user_id = uuid.uuid4()

    assert await limiter.allow(user_id)
    assert await limiter.allow(user_id)
    assert not await limiter.allow(user_id)
    assert await limiter.allow(uuid.uuid4())
