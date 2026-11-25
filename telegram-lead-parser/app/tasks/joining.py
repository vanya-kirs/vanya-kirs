"""
Auto-joining task: processes sources with status='pending' by joining them
via Telethon. At most _BATCH_SIZE sources per run, _DAILY_LIMIT per 24-hour
window (counter resets 24h after the first join, not at calendar midnight).

Status transitions:
  pending → active             (joined successfully or already a member)
  pending → dead               (banned / private / invite expired)
  pending → requires_approval  (private group, join request pending admin)
"""

import asyncio
import logging
import random

import httpx

from app.core.celery import celery_app
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

_BATCH_SIZE = 5        # max joins per single task run
_DAILY_LIMIT = 10      # max joins per rolling 24-hour window
_WINDOW_SECONDS = 86_400
_REDIS_KEY = "joining:24h_count"
_PAUSE_MIN = 15.0
_PAUSE_MAX = 40.0


@celery_app.task(
    bind=True,
    name="app.tasks.joining.process_pending_sources",
    max_retries=0,
)
def process_pending_sources(self) -> dict:
    """Every 30 min: join up to _DAILY_LIMIT pending sources per 24-hour window."""

    async def _run() -> dict:
        from datetime import datetime, timezone

        import redis.asyncio as aioredis
        from sqlalchemy import select, update
        from telethon.errors import (
            ChannelPrivateError,
            FloodWaitError,
            InviteHashExpiredError,
            UserAlreadyParticipantError,
            UserBannedInChannelError,
            UsernameNotOccupiedError,
        )
        from telethon.tl.functions.channels import JoinChannelRequest

        from app.core.config import get_settings
        from app.core.database import AsyncSessionLocal, dispose_engine
        from app.models.source import Source
        from app.parser.client import TelethonClient

        await dispose_engine()
        settings = get_settings()

        # ------------------------------------------------------------------ #
        # Check rolling 24-hour daily limit via Redis                         #
        # ------------------------------------------------------------------ #
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            count_today = int(await redis_client.get(_REDIS_KEY) or 0)
        except Exception as exc:
            logger.warning("process_pending_sources: redis unavailable: %s — skipping limit", exc)
            count_today = 0

        remaining = _DAILY_LIMIT - count_today
        if remaining <= 0:
            await redis_client.aclose()
            logger.info(
                "process_pending_sources: 24h limit reached (%d/%d) — skipping",
                count_today,
                _DAILY_LIMIT,
            )
            return {"joined": 0, "dead": 0, "skipped": 0, "approval": 0, "limit_reached": True}

        batch_limit = min(_BATCH_SIZE, remaining)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Source).where(Source.status == "pending").limit(batch_limit)
            )
            sources = list(result.scalars().all())

        if not sources:
            await redis_client.aclose()
            logger.info("process_pending_sources: no pending sources")
            return {"joined": 0, "dead": 0, "skipped": 0, "approval": 0}

        joined = dead = skipped = approval = 0
        now = datetime.now(timezone.utc)

        try:
            async with TelethonClient(
                api_id=settings.API_ID,
                api_hash=settings.API_HASH,
                session_string=settings.SESSION_STRING,
            ) as client:
                for i, src in enumerate(sources):
                    try:
                        await client._client(JoinChannelRequest(channel=src.url))
                        async with AsyncSessionLocal() as db:
                            await db.execute(
                                update(Source)
                                .where(Source.id == src.id)
                                .values(
                                    status="active",
                                    joined_at=now,
                                    parsing_enabled=True,
                                )
                            )
                            await db.commit()
                        logger.info(
                            "process_pending_sources: joined %s (id=%d)", src.url, src.id
                        )
                        joined += 1
                        # Increment rolling 24h counter; set TTL only on first join
                        try:
                            new_count = await redis_client.incr(_REDIS_KEY)
                            if new_count == 1:
                                await redis_client.expire(_REDIS_KEY, _WINDOW_SECONDS)
                        except Exception:
                            pass

                    except UserAlreadyParticipantError:
                        async with AsyncSessionLocal() as db:
                            await db.execute(
                                update(Source)
                                .where(Source.id == src.id)
                                .values(
                                    status="active",
                                    joined_at=now,
                                    parsing_enabled=True,
                                )
                            )
                            await db.commit()
                        logger.info(
                            "process_pending_sources: already member %s — activated", src.url
                        )
                        joined += 1

                    except UsernameNotOccupiedError:
                        # Username gone — try to find by stored tg_channel_id
                        old_url = src.url
                        new_username = None
                        if src.tg_channel_id and src.tg_access_hash:
                            new_username, _ = await client.resolve_by_entity(
                                src.tg_channel_id, src.tg_access_hash
                            )
                        if new_username:
                            new_url = f"@{new_username}"
                            async with AsyncSessionLocal() as db:
                                await db.execute(
                                    update(Source)
                                    .where(Source.id == src.id)
                                    .values(url=new_url)
                                )
                                await db.commit()
                            src.url = new_url
                            logger.info(
                                "process_pending_sources: renamed %s → %s, retrying join",
                                old_url, new_url,
                            )
                            # retry the join with the new URL
                            try:
                                await client._client(JoinChannelRequest(channel=new_url))
                                async with AsyncSessionLocal() as db:
                                    await db.execute(
                                        update(Source)
                                        .where(Source.id == src.id)
                                        .values(status="active", joined_at=now, parsing_enabled=True)
                                    )
                                    await db.commit()
                                joined += 1
                                try:
                                    new_count = await redis_client.incr(_REDIS_KEY)
                                    if new_count == 1:
                                        await redis_client.expire(_REDIS_KEY, _WINDOW_SECONDS)
                                except Exception:
                                    pass
                            except Exception as retry_exc:
                                logger.error(
                                    "process_pending_sources: retry join %s failed: %s",
                                    new_url, retry_exc,
                                )
                                skipped += 1
                        else:
                            async with AsyncSessionLocal() as db:
                                await db.execute(
                                    update(Source)
                                    .where(Source.id == src.id)
                                    .values(status="dead", is_active=False, parsing_enabled=False)
                                )
                                await db.commit()
                            logger.warning(
                                "process_pending_sources: %s not found — marked dead", old_url
                            )
                            dead += 1
                            from app.core.alerts import notify_admin
                            await notify_admin(
                                f"💀 <b>Источник не найден</b>\n\n"
                                f"<code>{old_url}</code> — юзернейм не существует, "
                                f"entity ID не найден.\n"
                                f"Источник деактивирован."
                            )

                    except (
                        UserBannedInChannelError,
                        InviteHashExpiredError,
                        ChannelPrivateError,
                    ) as exc:
                        async with AsyncSessionLocal() as db:
                            await db.execute(
                                update(Source)
                                .where(Source.id == src.id)
                                .values(
                                    status="dead",
                                    is_active=False,
                                    parsing_enabled=False,
                                )
                            )
                            await db.commit()
                        logger.warning(
                            "process_pending_sources: dead %s (%s)",
                            src.url,
                            type(exc).__name__,
                        )
                        dead += 1

                    except FloodWaitError as e:
                        wait = e.seconds + 10
                        logger.warning(
                            "process_pending_sources: FloodWait %ds — stopping batch "
                            "(processed %d/%d)",
                            wait,
                            i,
                            len(sources),
                        )
                        skipped += len(sources) - i
                        break

                    except Exception as exc:
                        exc_msg = str(exc).lower()
                        if "invite_request_sent" in exc_msg or "successfully requested" in exc_msg:
                            async with AsyncSessionLocal() as db:
                                await db.execute(
                                    update(Source)
                                    .where(Source.id == src.id)
                                    .values(
                                        status="requires_approval",
                                        requires_join=False,
                                    )
                                )
                                await db.commit()
                            logger.warning(
                                "process_pending_sources: requires admin approval %s", src.url
                            )
                            approval += 1
                        else:
                            logger.error(
                                "process_pending_sources: unexpected error %s: %s", src.url, exc
                            )
                            skipped += 1

                    if i < len(sources) - 1:
                        pause = random.uniform(_PAUSE_MIN, _PAUSE_MAX)
                        logger.debug(
                            "process_pending_sources: pause %.1fs before next join", pause
                        )
                        await asyncio.sleep(pause)

        finally:
            await redis_client.aclose()

        stats = {"joined": joined, "dead": dead, "skipped": skipped, "approval": approval}
        logger.info("process_pending_sources done: %s", stats)

        if (joined or dead or approval) and settings.BOT_TOKEN:
            text = (
                f"🔗 Автовступление\n"
                f"Вступил: {joined} · мёртвых: {dead} · "
                f"ожидает одобрения: {approval} · пропущено: {skipped}"
            )
            admins = settings.admin_ids or (
                [settings.OWNER_TELEGRAM_ID] if settings.OWNER_TELEGRAM_ID else []
            )
            proxy = settings.PROXY_URL or None
            async with httpx.AsyncClient(timeout=10, proxy=proxy) as http:
                for admin_id in admins:
                    try:
                        await http.post(
                            f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage",
                            json={"chat_id": admin_id, "text": text},
                        )
                    except Exception as exc:
                        logger.warning(
                            "process_pending_sources notify %d: %s", admin_id, exc
                        )

        return stats

    return asyncio.run(_run())
