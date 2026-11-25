import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_HOURLY_KEY = "parser:requests:hourly"
_DAILY_JOIN_KEY = "parser:joins:daily"
_JOIN_QUEUE_KEY = "parser:join_queue"
_HOURLY_LIMIT = 30
_DAILY_JOIN_LIMIT = 5
_HOURLY_TTL = 3600
_DAILY_TTL = 86400


class ParserRateLimiter:
    def __init__(self, redis_url: str, _client: aioredis.Redis | None = None) -> None:
        self._redis = _client or aioredis.from_url(redis_url, decode_responses=True)

    async def can_request(self) -> bool:
        count = await self._redis.get(_HOURLY_KEY)
        return (int(count) if count else 0) < _HOURLY_LIMIT

    async def increment_request(self) -> None:
        count = await self._redis.incr(_HOURLY_KEY)
        if count == 1:
            await self._redis.expire(_HOURLY_KEY, _HOURLY_TTL)

    async def can_join(self) -> bool:
        count = await self._redis.get(_DAILY_JOIN_KEY)
        return (int(count) if count else 0) < _DAILY_JOIN_LIMIT

    async def increment_join(self) -> None:
        count = await self._redis.incr(_DAILY_JOIN_KEY)
        if count == 1:
            await self._redis.expire(_DAILY_JOIN_KEY, _DAILY_TTL)

    async def get_request_count(self) -> int:
        count = await self._redis.get(_HOURLY_KEY)
        return int(count) if count else 0

    async def get_join_count(self) -> int:
        count = await self._redis.get(_DAILY_JOIN_KEY)
        return int(count) if count else 0

    async def enqueue_join(self, source_id: int, priority: int = 50) -> None:
        await self._redis.zadd(_JOIN_QUEUE_KEY, {str(source_id): priority})

    async def dequeue_join(self, source_id: int) -> None:
        await self._redis.zrem(_JOIN_QUEUE_KEY, str(source_id))

    async def set_priority(self, source_id: int, priority: int) -> None:
        await self._redis.zadd(_JOIN_QUEUE_KEY, {str(source_id): priority}, xx=True)

    async def peek_next_join(self) -> tuple[int, int] | None:
        items = await self._redis.zrange(_JOIN_QUEUE_KEY, 0, 0, withscores=True)
        if not items:
            return None
        source_id_str, score = items[0]
        return (int(source_id_str), int(score))

    async def list_queue(self) -> list[tuple[int, int]]:
        items = await self._redis.zrange(_JOIN_QUEUE_KEY, 0, -1, withscores=True)
        return [(int(sid), int(score)) for sid, score in items]

    async def is_queued(self, source_id: int) -> bool:
        score = await self._redis.zscore(_JOIN_QUEUE_KEY, str(source_id))
        return score is not None
