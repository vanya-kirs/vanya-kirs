import asyncio
import logging

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 3  # max parallel scoring tasks dispatched from listener
_PROFILE_PAUSE = 1.0  # seconds between bio fetch requests


class RateLimiter:
    """Semaphore-based concurrency limiter for Celery task dispatching."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT) -> None:
        self._sem = asyncio.Semaphore(max_concurrent)

    async def __aenter__(self) -> "RateLimiter":
        await self._sem.acquire()
        return self

    async def __aexit__(self, *_) -> None:
        self._sem.release()

    async def run(self, coro) -> None:
        """Acquire semaphore, run coroutine, release."""
        async with self:
            await coro
