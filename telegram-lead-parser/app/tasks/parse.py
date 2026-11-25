import asyncio
import logging

from telethon.errors import UsernameInvalidError

from app.core.celery import celery_app
from app.core.logging import setup_logging, setup_parser_file_logging

setup_logging()
setup_parser_file_logging()
logger = logging.getLogger(__name__)

_PARSE_LOCK_KEY = "parser:parsing_active"
_PARSE_LOCK_TTL = 1500  # 25-minute safety ceiling to avoid stuck locks


@celery_app.task(
    bind=True,
    name="app.tasks.parse.parse_source_task",
    max_retries=3,
    default_retry_delay=60,
)
def parse_source_task(self, source_id: int) -> dict:
    """Parse one source (sequential mode). Releases the global parse lock when done."""
    from app.core.config import get_settings
    from app.parser.service import ParserService

    settings = get_settings()

    async def _run():
        import redis.asyncio as aioredis

        from app.core.database import dispose_engine

        await dispose_engine()
        service = ParserService()
        try:
            return await service.parse_source(source_id=source_id)
        finally:
            redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            try:
                await redis_client.delete(_PARSE_LOCK_KEY)
                logger.debug("parse_source_task: released parse lock for source_id=%d", source_id)
            finally:
                await redis_client.aclose()

    try:
        result = asyncio.run(_run())
        outcome = "renamed" if result.renamed else ("lost" if result.lost else "ok")
        logger.info(
            "parse_source_task done: source_id=%d new=%d skipped=%d duration=%s outcome=%s",
            source_id,
            result.new,
            result.skipped,
            result.duration_seconds,
            outcome,
        )
        return {
            "source_id": result.source_id,
            "parsed": result.parsed,
            "new": result.new,
            "skipped": result.skipped,
            "duration_seconds": result.duration_seconds,
            "outcome": outcome,
        }
    except (UsernameInvalidError, ValueError) as exc:
        # UsernameNotOccupiedError is handled inside the service (rename detection).
        # This branch catches UsernameInvalidError (malformed URL) or unexpected ValueErrors.
        if not isinstance(exc, UsernameInvalidError) and "No user has" not in str(exc):
            logger.error("parse_source_task failed for source_id=%d: %s", source_id, exc)
            raise self.retry(exc=exc)
        logger.warning(
            "parse_source_task: invalid username for source_id=%d (%s), deactivating",
            source_id, exc,
        )
        async def _deactivate():
            from app.core.database import AsyncSessionLocal, dispose_engine
            from app.repositories.source import SourceRepository
            await dispose_engine()
            async with AsyncSessionLocal() as db:
                await SourceRepository.deactivate(db, source_id=source_id)
        asyncio.run(_deactivate())
        return {"source_id": source_id, "error": "invalid_username"}
    except Exception as exc:
        logger.error("parse_source_task failed for source_id=%d: %s", source_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(name="app.tasks.parse.schedule_parse_task")
def schedule_parse_task() -> dict:
    """Run every minute. If no parse is active, dispatch the most-overdue source."""
    from app.core.config import get_settings

    settings = get_settings()

    async def _run() -> dict:
        import redis.asyncio as aioredis

        from app.core.database import AsyncSessionLocal, dispose_engine
        from app.repositories.source import SourceRepository

        await dispose_engine()
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            if await redis_client.exists(_PARSE_LOCK_KEY):
                logger.debug("schedule_parse_task: parse lock held, skipping")
                return {"action": "locked"}

            async with AsyncSessionLocal() as db:
                due_sources = await SourceRepository.get_due_sources(db)

            if not due_sources:
                logger.debug("schedule_parse_task: no sources due")
                return {"action": "nothing_due"}

            source = due_sources[0]
            await redis_client.set(_PARSE_LOCK_KEY, str(source.id), ex=_PARSE_LOCK_TTL)
            parse_source_task.delay(source.id)
            logger.info(
                "schedule_parse_task: dispatched source_id=%d url=%s (interval=%dmin)",
                source.id,
                source.url,
                source.parse_interval_minutes,
            )
            return {"action": "dispatched", "source_id": source.id}
        finally:
            await redis_client.aclose()

    return asyncio.run(_run())


@celery_app.task(name="app.tasks.parse.parse_all_sources_task")
def parse_all_sources_task() -> dict:
    """Enqueue parse tasks for all active sources (manual trigger / legacy)."""
    from app.core.database import AsyncSessionLocal
    from app.repositories.source import SourceRepository

    async def _get_sources():
        from app.core.database import dispose_engine
        await dispose_engine()
        async with AsyncSessionLocal() as db:
            return await SourceRepository.get_all_active(db)

    sources = asyncio.run(_get_sources())
    for source in sources:
        parse_source_task.delay(source.id)

    logger.info("parse_all_sources_task: queued %d sources", len(sources))
    return {"queued": len(sources)}


@celery_app.task(name="app.tasks.parse.process_join_queue_task")
def process_join_queue_task() -> dict:
    """Pop highest-priority source from join queue and enqueue parse if daily limit allows."""
    from app.core.config import get_settings

    settings = get_settings()

    async def _run() -> dict:
        from app.parser.rate_limiter import ParserRateLimiter

        rate_limiter = ParserRateLimiter(redis_url=settings.REDIS_URL)
        item = await rate_limiter.peek_next_join()
        if item is None:
            logger.debug("process_join_queue_task: queue is empty")
            return {"action": "empty"}

        source_id, priority = item

        if not await rate_limiter.can_join():
            join_count = await rate_limiter.get_join_count()
            logger.warning(
                "process_join_queue_task: daily limit reached (%d/5), skipping source_id=%d",
                join_count,
                source_id,
            )
            return {"action": "limited", "source_id": source_id}

        await rate_limiter.dequeue_join(source_id)
        parse_source_task.delay(source_id)
        logger.info(
            "process_join_queue_task: dispatched parse for source_id=%d (priority=%d)",
            source_id,
            priority,
        )
        return {"action": "dispatched", "source_id": source_id}

    return asyncio.run(_run())


@celery_app.task(name="app.tasks.parse.validate_source_task")
def validate_source_task(source_url: str) -> dict:
    """Validate that a Telegram URL is accessible."""
    from app.core.config import get_settings
    from app.parser.client import TelethonClient

    settings = get_settings()

    async def _run():
        async with TelethonClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        ) as client:
            return await client.validate_source(source_url)

    result = asyncio.run(_run())
    if result.is_valid:
        logger.info(
            "validate_source_task: %s is valid (title=%r members=%s)",
            source_url,
            result.title,
            result.members_count,
        )
    else:
        logger.warning(
            "validate_source_task: %s is invalid — %s",
            source_url,
            result.error,
        )
    return {
        "is_valid": result.is_valid,
        "title": result.title,
        "members_count": result.members_count,
        "error": result.error,
    }