import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone

from telethon.errors import ChannelPrivateError, UsernameNotOccupiedError

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.parser.client import TelethonClient
from app.parser.exceptions import BannedError
from app.parser.rate_limiter import ParserRateLimiter
from app.parser.schemas import ParseResult
from app.repositories.message import MessageRepository
from app.repositories.source import SourceRepository

logger = logging.getLogger(__name__)


async def _notify(coro) -> None:
    """Fire-and-forget a notification coroutine."""
    try:
        await coro
    except Exception as exc:
        logger.error("notification error: %s", exc)


class ParserService:
    async def parse_source(self, source_id: int) -> ParseResult:
        start = time.monotonic()
        settings = get_settings()
        rate_limiter = ParserRateLimiter(redis_url=settings.REDIS_URL)

        async with AsyncSessionLocal() as db:
            source = await SourceRepository.get_by_id(db, source_id)
            if source is None:
                raise ValueError(f"Source {source_id} not found")

            # New channel: fetch last 15 messages with no date filter
            # Existing channel: fetch messages since last interval window
            if source.last_parsed_at is None:
                scrape_limit = 15
                cutoff_date = None
            else:
                scrape_limit = 500
                cutoff_date = datetime.now(timezone.utc) - timedelta(
                    minutes=source.parse_interval_minutes
                )

            logger.info(
                "[PARSE] source_id=%d url=%s interval=%dmin cutoff=%s",
                source_id,
                source.url,
                source.parse_interval_minutes,
                cutoff_date,
            )

            # --- Join flow for private channels ---
            if source.requires_join:
                if not await rate_limiter.can_join():
                    join_count = await rate_limiter.get_join_count()
                    logger.warning("[JOIN] daily limit reached (%d/5)", join_count)
                    duration = time.monotonic() - start
                    return ParseResult(
                        source_id=source_id,
                        parsed=0,
                        new=0,
                        skipped=0,
                        duration_seconds=round(duration, 2),
                        join_limited=True,
                    )

                async with TelethonClient(
                    api_id=settings.API_ID,
                    api_hash=settings.API_HASH,
                    session_string=settings.SESSION_STRING,
                ) as client:
                    join_delay = random.uniform(30.0, 60.0)
                    logger.info("[JOIN] joining %s, delay=%.0fs", source.url, join_delay)
                    await asyncio.sleep(join_delay)
                    try:
                        await client.join_channel(source.url)
                    except Exception as join_exc:
                        exc_str = str(join_exc)
                        if "ChannelPrivateError" in type(join_exc).__name__ or "private" in exc_str.lower():
                            logger.warning(
                                "[JOIN] %s is private/banned — marking dead: %s",
                                source.url, join_exc,
                            )
                            already_dead = source.status == "dead"
                            await SourceRepository.set_status(db, source_id, "dead")
                            await rate_limiter.dequeue_join(source_id)
                            if not already_dead:
                                from app.core.alerts import notify_admin
                                await notify_admin(
                                    f"🔒 <b>Канал недоступен</b>\n\n"
                                    f"<code>{source.url}</code> — приватный или бан.\n"
                                    f"Источник помечен как мёртвый."
                                )
                            duration = time.monotonic() - start
                            return ParseResult(
                                source_id=source_id, parsed=0, new=0, skipped=0,
                                duration_seconds=round(duration, 2),
                            )
                        raise

                await rate_limiter.increment_join()
                await rate_limiter.dequeue_join(source_id)
                await SourceRepository.update_join_fields(
                    db, source_id, requires_join=False, join_queued_at=None
                )

            # --- Parse messages ---
            try:
                async with TelethonClient(
                    api_id=settings.API_ID,
                    api_hash=settings.API_HASH,
                    session_string=settings.SESSION_STRING,
                ) as client:
                    # Resolve entity on first scrape to persist the stable Telegram ID.
                    # This allows rename detection if the username changes later.
                    if source.tg_channel_id is None:
                        tg_id, tg_hash = await client.get_channel_entity(source.url)
                        if tg_id and tg_hash:
                            await SourceRepository.update_tg_entity(
                                db, source_id, tg_id, tg_hash
                            )
                            # Refresh in-memory copy so rename branch below sees it
                            source.tg_channel_id = tg_id
                            source.tg_access_hash = tg_hash

                    messages = await client.scrape_messages(
                        source.url,
                        limit=scrape_limit,
                        offset_date=cutoff_date,
                    )
                    logger.info(
                        "Scraped %d messages from %s (cutoff=%s)",
                        len(messages),
                        source.url,
                        cutoff_date,
                    )

            except ChannelPrivateError:
                now = datetime.now(timezone.utc)
                await SourceRepository.update_join_fields(
                    db, source_id, requires_join=True, join_queued_at=now
                )
                await rate_limiter.enqueue_join(source_id=source_id, priority=50)
                logger.warning("[JOIN] source_id=%d queued, priority=50", source_id)
                duration = time.monotonic() - start
                return ParseResult(
                    source_id=source_id,
                    parsed=0,
                    new=0,
                    skipped=0,
                    duration_seconds=round(duration, 2),
                    queued=True,
                )

            except UsernameNotOccupiedError:
                return await self._handle_username_gone(
                    db=db,
                    source=source,
                    source_id=source_id,
                    settings=settings,
                    scrape_limit=scrape_limit,
                    cutoff_date=cutoff_date,
                    start=start,
                )

            except BannedError:
                logger.critical("[BAN] UserDeactivatedBanError — stopping")
                raise

            new_messages = []
            skipped = 0
            for msg in messages:
                if await MessageRepository.exists(db, msg.tg_message_id, source_id):
                    skipped += 1
                else:
                    new_messages.append(msg)

            inserted = await MessageRepository.bulk_create(db, new_messages, source_id)

            # Don't advance last_parsed_at on the very first scrape if we got nothing —
            # next run would switch to the interval window and permanently skip history.
            if messages or source.last_parsed_at is not None:
                max_tg_id = max((m.tg_message_id for m in messages), default=None)
                await SourceRepository.update_last_parsed(
                    db,
                    source_id,
                    datetime.now(timezone.utc),
                    last_tg_message_id=max_tg_id,
                )
            else:
                logger.warning(
                    "[PARSE] first scrape returned 0 messages for source_id=%d — not advancing last_parsed_at",
                    source_id,
                )

            # Update adaptive interval based on message volume
            if len(messages) >= 20:
                new_interval = 5
            elif len(messages) >= 5:
                new_interval = 10
            else:
                new_interval = 15
            await SourceRepository.update_parse_interval(db, source_id, new_interval)
            logger.info(
                "[PARSE] interval updated to %dmin for source_id=%d (messages=%d)",
                new_interval,
                source_id,
                len(messages),
            )

        duration = time.monotonic() - start
        result = ParseResult(
            source_id=source_id,
            parsed=len(messages),
            new=inserted,
            skipped=skipped,
            duration_seconds=round(duration, 2),
        )
        logger.info(
            "[PARSE] done: parsed=%d new=%d skipped=%d",
            result.parsed,
            result.new,
            result.skipped,
        )
        return result

    async def _handle_username_gone(
        self, *, db, source, source_id: int, settings, scrape_limit: int, cutoff_date, start: float
    ) -> ParseResult:
        """Handle UsernameNotOccupiedError: try to find channel by entity ID, notify admin."""
        from aiogram import Bot
        from app.bot.handlers.notifications import (
            send_channel_lost_notification,
            send_channel_renamed_notification,
        )

        logger.warning(
            "[RENAME] UsernameNotOccupiedError for source_id=%d url=%s",
            source_id,
            source.url,
        )

        old_url = source.url
        source_name = source.name

        # Try to find the channel by its stable Telegram ID
        new_username: str | None = None
        new_title: str | None = None

        if source.tg_channel_id and source.tg_access_hash:
            async with TelethonClient(
                api_id=settings.API_ID,
                api_hash=settings.API_HASH,
                session_string=settings.SESSION_STRING,
            ) as client:
                new_username, new_title = await client.resolve_by_entity(
                    source.tg_channel_id, source.tg_access_hash
                )
        else:
            logger.warning(
                "[RENAME] no tg_channel_id stored for source_id=%d — cannot resolve",
                source_id,
            )

        bot = Bot(token=settings.BOT_TOKEN)
        try:
            if new_username:
                new_url = f"@{new_username}"
                await SourceRepository.update_url(db, source_id, new_url)
                logger.info(
                    "[RENAME] source_id=%d renamed %s → %s (title=%r)",
                    source_id,
                    old_url,
                    new_url,
                    new_title,
                )
                await _notify(
                    send_channel_renamed_notification(bot, source_name, old_url, new_url)
                )

                # Scrape with the new URL right away
                try:
                    async with TelethonClient(
                        api_id=settings.API_ID,
                        api_hash=settings.API_HASH,
                        session_string=settings.SESSION_STRING,
                    ) as client:
                        messages = await client.scrape_messages(
                            new_url, limit=scrape_limit, offset_date=cutoff_date
                        )
                except Exception as exc:
                    logger.error("[RENAME] scrape after rename failed: %s", exc)
                    messages = []

                new_messages = []
                skipped = 0
                for msg in messages:
                    if await MessageRepository.exists(db, msg.tg_message_id, source_id):
                        skipped += 1
                    else:
                        new_messages.append(msg)

                inserted = await MessageRepository.bulk_create(db, new_messages, source_id)
                if messages:
                    await SourceRepository.update_last_parsed(
                        db, source_id, datetime.now(timezone.utc),
                        last_tg_message_id=max((m.tg_message_id for m in messages), default=None),
                    )
                duration = time.monotonic() - start
                return ParseResult(
                    source_id=source_id,
                    parsed=len(messages),
                    new=inserted,
                    skipped=skipped,
                    duration_seconds=round(duration, 2),
                    renamed=True,
                )
            else:
                # Channel truly gone — deactivate and notify
                await SourceRepository.deactivate(db, source_id)
                logger.warning(
                    "[RENAME] source_id=%d not found by entity ID — deactivated",
                    source_id,
                )
                await _notify(
                    send_channel_lost_notification(
                        bot, source_name, old_url, source.tg_channel_id
                    )
                )
                duration = time.monotonic() - start
                return ParseResult(
                    source_id=source_id,
                    parsed=0,
                    new=0,
                    skipped=0,
                    duration_seconds=round(duration, 2),
                    lost=True,
                )
        finally:
            await bot.session.close()
