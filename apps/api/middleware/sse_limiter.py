"""Per-user concurrent SSE stream limiter."""

import asyncio
import uuid
from collections import defaultdict

MAX_CONCURRENT_STREAMS = 3

_user_streams: dict[uuid.UUID, int] = defaultdict(int)
_lock = asyncio.Lock()


class StreamLimitExceeded(Exception):
    pass


class StreamSlot:
    """Async context manager that acquires/releases a stream slot for a user."""

    def __init__(self, user_id: uuid.UUID):
        self.user_id = user_id
        self.acquired = False

    async def __aenter__(self):
        async with _lock:
            if _user_streams[self.user_id] >= MAX_CONCURRENT_STREAMS:
                raise StreamLimitExceeded()
            _user_streams[self.user_id] += 1
            self.acquired = True
        return self

    async def __aexit__(self, *args):
        if self.acquired:
            async with _lock:
                _user_streams[self.user_id] -= 1
                if _user_streams[self.user_id] <= 0:
                    del _user_streams[self.user_id]
