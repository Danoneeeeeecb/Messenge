import asyncio
import time
import uuid
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, count: int, window_seconds: int) -> None:
        self._count = count
        self._window_seconds = window_seconds
        self._events: dict[uuid.UUID, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: uuid.UUID) -> bool:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._count:
                return False
            events.append(now)
            return True
