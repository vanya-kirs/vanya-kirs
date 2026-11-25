import pytest
import fakeredis.aioredis

from app.parser.rate_limiter import ParserRateLimiter


@pytest.fixture
async def limiter():
    fake_redis = fakeredis.aioredis.FakeRedis()
    return ParserRateLimiter(redis_url="redis://localhost", _client=fake_redis)


async def test_can_request_initially_true(limiter):
    assert await limiter.can_request() is True


async def test_increment_request_blocks_at_limit(limiter):
    for _ in range(30):
        await limiter.increment_request()
    assert await limiter.can_request() is False


async def test_can_join_initially_true(limiter):
    assert await limiter.can_join() is True


async def test_increment_join_blocks_at_limit(limiter):
    for _ in range(5):
        await limiter.increment_join()
    assert await limiter.can_join() is False


async def test_get_request_count(limiter):
    await limiter.increment_request()
    await limiter.increment_request()
    assert await limiter.get_request_count() == 2


async def test_get_join_count(limiter):
    await limiter.increment_join()
    assert await limiter.get_join_count() == 1


async def test_enqueue_and_peek(limiter):
    await limiter.enqueue_join(source_id=42, priority=50)
    result = await limiter.peek_next_join()
    assert result == (42, 50)


async def test_peek_returns_none_when_empty(limiter):
    result = await limiter.peek_next_join()
    assert result is None


async def test_dequeue_removes_item(limiter):
    await limiter.enqueue_join(source_id=10, priority=1)
    await limiter.dequeue_join(source_id=10)
    assert await limiter.peek_next_join() is None


async def test_set_priority(limiter):
    await limiter.enqueue_join(source_id=7, priority=50)
    await limiter.set_priority(source_id=7, priority=1)
    result = await limiter.peek_next_join()
    assert result == (7, 1)


async def test_list_queue_order(limiter):
    await limiter.enqueue_join(source_id=5, priority=99)
    await limiter.enqueue_join(source_id=3, priority=1)
    await limiter.enqueue_join(source_id=8, priority=50)
    items = await limiter.list_queue()
    source_ids = [s for s, _ in items]
    assert source_ids == [3, 8, 5]


async def test_is_queued_true_and_false(limiter):
    await limiter.enqueue_join(source_id=99, priority=50)
    assert await limiter.is_queued(source_id=99) is True
    assert await limiter.is_queued(source_id=1) is False


async def test_peek_returns_lowest_priority_first(limiter):
    await limiter.enqueue_join(source_id=20, priority=80)
    await limiter.enqueue_join(source_id=21, priority=10)
    result = await limiter.peek_next_join()
    assert result == (21, 10)
