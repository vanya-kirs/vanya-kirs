import asyncio
import logging
import random

import httpx
from telethon.errors import FloodWaitError

from app.core.celery import celery_app
from app.core.logging import setup_logging, setup_parser_file_logging

setup_logging()
setup_parser_file_logging()
logger = logging.getLogger(__name__)

_SEEN_KEY_PREFIX = "global_search:seen"
_SEEN_TTL = 30 * 24 * 3600  # 30 days
_MAX_REQUESTS = 50
_MIN_MEMBERS = 100


@celery_app.task(
    bind=True,
    name="app.tasks.global_search.global_search_task",
    max_retries=1,
    default_retry_delay=300,
)
def global_search_task(self) -> dict:
    """Search Telegram globally using POSITIVE_KEYWORDS, save qualifying channels and score messages."""

    async def _run() -> dict:
        import redis.asyncio as aioredis

        from app.core.config import get_settings
        from app.core.database import AsyncSessionLocal, dispose_engine
        from app.parser.client import TelethonClient
        from app.parser.schemas import MessageData
        from app.repositories.message import MessageRepository
        from app.repositories.source import SourceRepository
        from app.repositories.user import UserRepository
        from app.scoring.keyword_filter import POSITIVE_KEYWORDS

        await dispose_engine()
        settings = get_settings()
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

        # Resolve owner user record
        async with AsyncSessionLocal() as db:
            owner = await UserRepository.get_by_telegram_id(db, settings.OWNER_TELEGRAM_ID)
            if owner is None:
                logger.error("global_search_task: owner user not found (OWNER_TELEGRAM_ID=%d)", settings.OWNER_TELEGRAM_ID)
                return {"error": "owner_not_found"}
            user_id = owner.id

        stats = {"keywords_searched": 0, "messages_found": 0, "sources_added": 0, "messages_stored": 0}
        request_count = 0
        sources_with_new_msgs: set[int] = set()

        async with TelethonClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        ) as client:
            for keyword in POSITIVE_KEYWORDS:
                if request_count >= _MAX_REQUESTS:
                    logger.info("global_search_task: request limit reached (%d)", _MAX_REQUESTS)
                    break

                # --- Search Telegram globally ---
                try:
                    results = await client.search_global_messages(keyword, limit=20)
                    request_count += 1
                    stats["keywords_searched"] += 1
                except FloodWaitError as e:
                    wait = e.seconds + 5
                    logger.warning("[FLOOD] global_search waiting %ds for keyword %r", wait, keyword)
                    await asyncio.sleep(wait)
                    try:
                        results = await client.search_global_messages(keyword, limit=20)
                        request_count += 1
                        stats["keywords_searched"] += 1
                    except Exception as exc:
                        logger.error("global_search retry failed for %r: %s", keyword, exc)
                        results = []
                except Exception as exc:
                    logger.error("global_search failed for %r: %s", keyword, exc)
                    results = []

                stats["messages_found"] += len(results)

                for msg in results:
                    # --- Deduplication ---
                    seen_key = f"{_SEEN_KEY_PREFIX}:{msg.chat_id}:{msg.message_id}"
                    if await redis_client.exists(seen_key):
                        continue
                    await redis_client.set(seen_key, "1", ex=_SEEN_TTL)

                    # --- Filter: only public channels with enough members ---
                    if not msg.chat_username:
                        continue
                    if (msg.chat_members or 0) < _MIN_MEMBERS:
                        continue

                    url = f"@{msg.chat_username}"

                    async with AsyncSessionLocal() as db:
                        source = await SourceRepository.get_or_create_for_global_search(
                            db, url, msg.chat_title or url, user_id
                        )

                        msg_data = MessageData(
                            tg_message_id=msg.message_id,
                            text=msg.message_text,
                            tg_date=msg.message_date,
                            sender_id=None,
                            sender_name="",
                            sender_username=None,
                        )
                        inserted = await MessageRepository.bulk_create(db, [msg_data], source.id)
                        if inserted > 0:
                            stats["messages_stored"] += inserted
                            sources_with_new_msgs.add(source.id)
                            if source.discovery_method == "global_search":
                                stats["sources_added"] += 1

                # --- Rate limiting pause ---
                pause = random.uniform(10, 20)
                logger.debug("global_search: pause %.1fs after keyword %r", pause, keyword)
                await asyncio.sleep(pause)

        await redis_client.aclose()

        # Trigger scoring for sources that received new messages
        if sources_with_new_msgs:
            from app.tasks.score import score_source_task
            for source_id in sources_with_new_msgs:
                score_source_task.delay(source_id, user_id)
            logger.info("global_search_task: queued scoring for %d sources", len(sources_with_new_msgs))

        logger.info(
            "global_search_task done: %s",
            " ".join(f"{k}={v}" for k, v in stats.items()),
        )

        # Notify all admins with a summary
        admins = settings.admin_ids or (
            [settings.OWNER_TELEGRAM_ID] if settings.OWNER_TELEGRAM_ID else []
        )
        if admins and settings.BOT_TOKEN:
            text = (
                f"🔍 Глобальный поиск завершён\n"
                f"Ключевых слов: {stats['keywords_searched']}\n"
                f"Найдено сообщений: {stats['messages_found']}\n"
                f"Новых каналов: {stats['sources_added']}\n"
                f"Сохранено сообщений: {stats['messages_stored']}"
            )
            tg_url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
            proxy = settings.PROXY_URL or None
            with httpx.Client(timeout=15, proxy=proxy) as http_cl:
                for admin_id in admins:
                    try:
                        http_cl.post(tg_url, json={"chat_id": admin_id, "text": text})
                    except Exception as exc:
                        logger.warning("global_search notify failed for %d: %s", admin_id, exc)

        return stats

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("global_search_task failed: %s", exc)
        raise self.retry(exc=exc)
