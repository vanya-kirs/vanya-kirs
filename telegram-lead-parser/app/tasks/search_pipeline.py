"""
Day-scheduler for Telegram global keyword search via Pyrogram.

Usage (standalone):
    import asyncpg
    from pyrogram import Client

    async def main():
        app = Client("my_session", api_id=..., api_hash=...)
        conn = await asyncpg.connect("postgresql://...")
        async with app:
            await run_day_scheduler(app, conn)

    asyncio.run(main())
"""

import asyncio
import logging
import random
from datetime import datetime

logger = logging.getLogger(__name__)

# ── constants ──────────────────────────────────────────────────────────────
_MIN_MEMBERS = 100
_MAX_REQUESTS_PER_SESSION = 50
_SEEN_KEY_PREFIX = "global_search:seen"
_SEEN_TTL = 30 * 24 * 3600          # 30 days

_DAY_START_MIN = 9 * 60             # 09:00  → 540 min from midnight
_DAY_END_MIN = 22 * 60              # 22:00  → 1320 min from midnight
_MIN_GAP_MINUTES = 90

_CREATE_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS search_sessions (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    keywords_used   TEXT[],
    messages_found  INTEGER DEFAULT 0,
    sources_added   INTEGER DEFAULT 0,
    leads_added     INTEGER DEFAULT 0,
    watch_added     INTEGER DEFAULT 0
);
"""


# ── helpers ────────────────────────────────────────────────────────────────

async def _ensure_tables(conn) -> None:
    await conn.execute(_CREATE_SESSIONS_SQL)


def _plan_day_schedule() -> list[datetime]:
    """
    Plan 4-7 random run times between 09:00-22:00 today.
    Guarantees >= 90 min between any two consecutive runs.
    """
    n = random.randint(4, 7)

    # Rejection sampling: try to find a valid arrangement
    for _ in range(500):
        candidates = sorted(
            random.randint(_DAY_START_MIN, _DAY_END_MIN) for _ in range(n)
        )
        if all(
            candidates[i] - candidates[i - 1] >= _MIN_GAP_MINUTES
            for i in range(1, n)
        ):
            break
    else:
        # Deterministic fallback: evenly space runs
        step = (_DAY_END_MIN - _DAY_START_MIN) // (n + 1)
        candidates = [_DAY_START_MIN + step * (i + 1) for i in range(n)]

    today = datetime.now().date()
    result = []
    for mins in candidates:
        h, m = divmod(mins, 60)
        dt = datetime(today.year, today.month, today.day, h, m, random.randint(0, 59))
        result.append(dt)

    logger.info(
        "Day schedule: %d runs at %s",
        n,
        [t.strftime("%H:%M") for t in result],
    )
    return result


# ── core pipeline ──────────────────────────────────────────────────────────

async def run_search_pipeline(app, conn, keywords: list[str]) -> dict:
    """
    One global-search session.

    Parameters
    ----------
    app      : Connected Pyrogram Client
    conn     : asyncpg connection (write access to sources / messages tables)
    keywords : list of keywords to search this session

    Returns
    -------
    dict
        messages_found  — unique messages processed
        sources_added   — new sources written to DB
        leads_added     — messages that passed keyword pre-filter (queued for AI)
        watch_added     — channels found but below member threshold (not saved)
    """
    from app.core.config import get_settings
    from app.scoring.keyword_filter import keyword_prefilter

    import redis.asyncio as aioredis

    settings = get_settings()
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    stats = {
        "messages_found": 0,
        "sources_added":  0,
        "leads_added":    0,
        "watch_added":    0,
    }
    request_count = 0

    # Resolve owner's internal user id once
    owner_user_id: int | None = await conn.fetchval(
        "SELECT id FROM users WHERE telegram_id = $1 LIMIT 1",
        settings.OWNER_TELEGRAM_ID,
    )
    if owner_user_id is None:
        logger.error("run_search_pipeline: owner not found (OWNER_TELEGRAM_ID=%d)", settings.OWNER_TELEGRAM_ID)
        await redis_client.aclose()
        return stats

    try:
        for keyword in keywords:
            if request_count >= _MAX_REQUESTS_PER_SESSION:
                logger.info("run_search_pipeline: request limit (%d) reached", _MAX_REQUESTS_PER_SESSION)
                break

            # ── Telegram global search ─────────────────────────────────────
            messages: list = []
            try:
                async for msg in app.search_global(keyword, limit=20):
                    messages.append(msg)
                request_count += 1
            except Exception as exc:
                wait = getattr(exc, "value", None)   # Pyrogram FloodWait.value
                if wait is not None:
                    logger.warning("[FLOOD] %ds for keyword %r — waiting", wait, keyword)
                    await asyncio.sleep(int(wait) + 5)
                    try:
                        async for msg in app.search_global(keyword, limit=20):
                            messages.append(msg)
                        request_count += 1
                    except Exception as exc2:
                        logger.error("Retry failed for %r: %s", keyword, exc2)
                else:
                    logger.error("search_global error for %r: %s", keyword, exc)

            # ── Process messages ───────────────────────────────────────────
            for msg in messages:
                text = getattr(msg, "text", None) or getattr(msg, "caption", None)
                if not text:
                    continue

                chat = getattr(msg, "chat", None)
                if chat is None:
                    continue

                # Deduplication via Redis
                seen_key = f"{_SEEN_KEY_PREFIX}:{chat.id}:{msg.id}"
                if await redis_client.exists(seen_key):
                    continue
                await redis_client.set(seen_key, "1", ex=_SEEN_TTL)

                stats["messages_found"] += 1

                members  = getattr(chat, "members_count", 0) or 0
                username = getattr(chat, "username", None)
                title    = getattr(chat, "title", None) or username or str(chat.id)

                if username and members >= _MIN_MEMBERS:
                    # ── Eligible channel → save source + message ──────────
                    url = f"@{username}"

                    source_id: int | None = await conn.fetchval(
                        "SELECT id FROM sources WHERE url = $1", url
                    )

                    if source_id is None:
                        await conn.execute(
                            """
                            INSERT INTO sources
                                (url, name, user_id, is_active, parsing_enabled,
                                 parse_interval_minutes, discovery_method, requires_join)
                            VALUES ($1, $2, $3, TRUE, TRUE, 15, 'global_search', FALSE)
                            ON CONFLICT (url) DO NOTHING
                            """,
                            url, title, owner_user_id,
                        )
                        source_id = await conn.fetchval(
                            "SELECT id FROM sources WHERE url = $1", url
                        )
                        if source_id:
                            stats["sources_added"] += 1
                            logger.info("global_search: new source %s (id=%d)", url, source_id)

                    if source_id:
                        new_msg_id: int | None = await conn.fetchval(
                            """
                            INSERT INTO messages
                                (source_id, tg_message_id, text, tg_date, is_scored)
                            VALUES ($1, $2, $3, $4, FALSE)
                            ON CONFLICT (source_id, tg_message_id) DO NOTHING
                            RETURNING id
                            """,
                            source_id,
                            msg.id,
                            text,
                            msg.date,
                        )
                        if new_msg_id:
                            # Count as lead candidate if it passes keyword pre-filter
                            passed, _ = keyword_prefilter(text)
                            if passed:
                                stats["leads_added"] += 1

                else:
                    # ── Below threshold → watch count only ────────────────
                    if username:
                        stats["watch_added"] += 1

            # Rate-limiting pause between keywords
            pause = random.uniform(10, 20)
            logger.debug("Pause %.1fs after %r", pause, keyword)
            await asyncio.sleep(pause)

    finally:
        await redis_client.aclose()

    return stats


# ── day scheduler ──────────────────────────────────────────────────────────

async def run_day_scheduler(app, conn) -> None:
    """
    Schedule and execute run_search_pipeline several times today.

    Runs 4-7 times between 09:00-22:00 with at least 90 min between sessions.
    Each session uses a random slice of 5-12 POSITIVE_KEYWORDS.
    Results are logged to the search_sessions table and sent as a Telegram
    self-message.

    Parameters
    ----------
    app  : Connected Pyrogram Client  (used for search + send_message)
    conn : asyncpg connection          (DB logging + source/message writes)
    """
    from app.scoring.keyword_filter import POSITIVE_KEYWORDS

    await _ensure_tables(conn)

    schedule = _plan_day_schedule()
    now = datetime.now()
    upcoming = [t for t in schedule if t > now]

    logger.info(
        "run_day_scheduler: %d sessions planned, %d still upcoming",
        len(schedule),
        len(upcoming),
    )

    for run_time in upcoming:
        wait_secs = (run_time - datetime.now()).total_seconds()
        if wait_secs > 0:
            logger.info(
                "Next session at %s (%.0f min away)",
                run_time.strftime("%H:%M"),
                wait_secs / 60,
            )
            await asyncio.sleep(wait_secs)

        # Random keyword slice for this session
        n_kw = random.randint(5, 12)
        keywords = random.sample(POSITIVE_KEYWORDS, min(n_kw, len(POSITIVE_KEYWORDS)))

        started_at = datetime.now()
        logger.info(
            "Session started at %s with %d keywords",
            started_at.strftime("%H:%M:%S"),
            len(keywords),
        )

        try:
            stats = await run_search_pipeline(app, conn, keywords)
        except Exception as exc:
            logger.error("run_search_pipeline raised: %s", exc)
            stats = {
                "messages_found": 0,
                "sources_added":  0,
                "leads_added":    0,
                "watch_added":    0,
            }

        finished_at = datetime.now()

        # ── PostgreSQL session log ─────────────────────────────────────────
        try:
            await conn.execute(
                """
                INSERT INTO search_sessions
                    (started_at, finished_at, keywords_used,
                     messages_found, sources_added, leads_added, watch_added)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                started_at,
                finished_at,
                keywords,
                stats["messages_found"],
                stats["sources_added"],
                stats["leads_added"],
                stats["watch_added"],
            )
            logger.debug("Session logged to search_sessions")
        except Exception as exc:
            logger.error("Failed to log session: %s", exc)

        # ── Telegram self-notification ─────────────────────────────────────
        notification = (
            f"🔍 Сессия завершена\n"
            f"🕐 {finished_at.strftime('%H:%M')}\n"
            f"🔑 Ключевых слов: {len(keywords)}\n"
            f"📨 Сообщений найдено: {stats['messages_found']}\n"
            f"📥 Новых источников: {stats['sources_added']}\n"
            f"✅ Лидов: {stats['leads_added']}\n"
            f"👁 Наблюдать: {stats['watch_added']}"
        )
        try:
            await app.send_message("me", notification)
            logger.info("Session notification sent")
        except Exception as exc:
            logger.error("Failed to send notification: %s", exc)

    logger.info("run_day_scheduler: all sessions completed for today")
