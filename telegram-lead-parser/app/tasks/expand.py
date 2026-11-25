"""
Automatic source expansion tasks.

Each task finds new Telegram chats and adds them via
INSERT ... ON CONFLICT DO NOTHING (idempotent by url).

Filters (Telethon-based tasks): public username, group/supergroup,
members_count >= MIN_MEMBERS_COUNT (config).
"""

import asyncio
import logging
import random
import re

import httpx
from telethon.errors import FloodWaitError

from app.core.celery import celery_app
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

_USERNAME_RE = re.compile(r"@([a-zA-Z0-9_]{5,32})")
_TGSTAT_CHAT_RE = re.compile(r"tgstat\.ru/en/chat/@([a-zA-Z0-9_]{5,32})")
_GOOGLE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_GOOGLE_TGSTAT_QUERIES = [
    "site:tgstat.ru/en/chat предприниматели",
    "site:tgstat.ru/en/chat собственники бизнес",
    "site:tgstat.ru/en/chat личностный рост",
    "site:tgstat.ru/en/chat выгорание",
    "site:tgstat.ru/en/chat инвестиции нетворкинг",
    "site:tgstat.ru/en/chat карьера управление",
    "site:tgstat.ru/en/chat мастермайнд",
    "site:tgstat.ru/en/chat коучинг",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _is_group(entity) -> bool:
    """True if entity is a group or supergroup (not a broadcast channel)."""
    from telethon.tl.types import Channel, Chat
    if isinstance(entity, Chat):
        return True
    if isinstance(entity, Channel):
        return not getattr(entity, "broadcast", True)
    return False


async def _bulk_insert(
    candidates: list[dict],
    user_id: int,
    discovery_method: str,
    min_members: int,
) -> dict:
    """
    INSERT candidates into sources with ON CONFLICT DO NOTHING.
    candidates: [{"url": str, "name": str}]
    Returns {"added": int, "already_exists": int}.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.core.database import AsyncSessionLocal
    from app.models.source import Source

    added = already_exists = 0
    async with AsyncSessionLocal() as db:
        for c in candidates:
            stmt = (
                pg_insert(Source)
                .values(
                    url=c["url"],
                    name=c["name"],
                    user_id=user_id,
                    discovery_method=discovery_method,
                    status="pending",
                    parsing_enabled=False,
                    is_active=True,
                )
                .on_conflict_do_nothing(index_elements=["url"])
                .returning(Source.id)
            )
            result = await db.execute(stmt)
            if result.scalar_one_or_none() is not None:
                added += 1
            else:
                already_exists += 1
        await db.commit()
    return {"added": added, "already_exists": already_exists}


async def _bulk_insert_rejected(items: list[dict]) -> int:
    """Upsert rejected candidates into rejected_sources."""
    if not items:
        return 0
    from app.core.database import AsyncSessionLocal
    from app.repositories.rejected_source import RejectedSourceRepository

    async with AsyncSessionLocal() as db:
        return await RejectedSourceRepository.bulk_upsert(db, items)


async def _notify(settings, text: str) -> None:
    tg_url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    admins = settings.admin_ids or (
        [settings.OWNER_TELEGRAM_ID] if settings.OWNER_TELEGRAM_ID else []
    )
    if not admins:
        return
    proxy = settings.PROXY_URL or None
    async with httpx.AsyncClient(timeout=15, proxy=proxy) as client:
        for admin_id in admins:
            try:
                await client.post(tg_url, json={"chat_id": admin_id, "text": text})
            except Exception as exc:
                logger.warning("expand notify admin %d: %s", admin_id, exc)


async def _resolve_owner(settings) -> int | None:
    from app.core.database import AsyncSessionLocal
    from app.repositories.user import UserRepository

    async with AsyncSessionLocal() as db:
        owner = await UserRepository.get_by_telegram_id(db, settings.OWNER_TELEGRAM_ID)
        return owner.id if owner else None


# ---------------------------------------------------------------------------
# Task 1 — Recommendations
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="app.tasks.expand.expand_from_recommendations",
    max_retries=1,
    default_retry_delay=300,
)
def expand_from_recommendations(self) -> dict:
    """Weekly: GetChannelRecommendations for every active source."""

    async def _run() -> dict:
        from telethon.tl.functions.channels import GetChannelRecommendationsRequest

        from app.core.config import get_settings
        from app.core.database import AsyncSessionLocal, dispose_engine
        from app.parser.client import TelethonClient
        from app.repositories.source import SourceRepository

        await dispose_engine()
        settings = get_settings()
        min_members = settings.EXPAND_MIN_MEMBERS

        user_id = await _resolve_owner(settings)
        if user_id is None:
            return {"error": "owner_not_found"}

        async with AsyncSessionLocal() as db:
            sources = await SourceRepository.get_all_active(db, user_id=user_id)

        candidates: list[dict] = []
        rejected_items: list[dict] = []
        checked = rejected_private = rejected_small = rejected_not_group = 0

        async with TelethonClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        ) as client:
            for src in sources:
                try:
                    entity = await client._client.get_entity(src.url)
                    result = await client._client(
                        GetChannelRecommendationsRequest(channel=entity)
                    )
                    for ch in result.chats:
                        checked += 1
                        username = getattr(ch, "username", None)
                        members = getattr(ch, "participants_count", None)
                        if not username:
                            rejected_private += 1
                            continue
                        if members is not None and members < min_members:
                            rejected_small += 1
                            rejected_items.append({
                                "url": f"@{username}",
                                "name": getattr(ch, "title", username),
                                "reason": "too_small",
                                "member_count": members or 0,
                                "discovery_method": "expand_recommendations",
                            })
                            continue
                        if not _is_group(ch):
                            rejected_not_group += 1
                            rejected_items.append({
                                "url": f"@{username}",
                                "name": getattr(ch, "title", username),
                                "reason": "broadcast",
                                "member_count": members or 0,
                                "discovery_method": "expand_recommendations",
                            })
                            continue
                        candidates.append(
                            {"url": f"@{username}", "name": getattr(ch, "title", username)}
                        )
                    await asyncio.sleep(random.uniform(2, 5))
                except FloodWaitError as e:
                    wait = e.seconds + 10
                    logger.warning("expand_recommendations FloodWait %ds for %s", wait, src.url)
                    await asyncio.sleep(wait)
                except Exception as exc:
                    logger.debug("expand_recommendations error for %s: %s", src.url, exc)

        ins = await _bulk_insert(candidates, user_id, "expand_recommendations", min_members)
        await _bulk_insert_rejected(rejected_items)
        stats = {
            "sources_processed": len(sources),
            "candidates_checked": checked,
            "added": ins["added"],
            "already_exists": ins["already_exists"],
            "rejected_private": rejected_private,
            "rejected_small": rejected_small,
            "rejected_not_group": rejected_not_group,
        }
        logger.info("expand_from_recommendations done: %s", stats)
        await _notify(
            settings,
            f"📡 Расширение: рекомендации\n"
            f"Источников: {len(sources)} · кандидатов: {checked}\n"
            f"Добавлено: {ins['added']} · уже было: {ins['already_exists']}\n"
            f"Откл.: приватных {rejected_private}, маленьких {rejected_small}, "
            f"не группа {rejected_not_group}",
        )
        return stats

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("expand_from_recommendations failed: %s", exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Task 2 — Forwards
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="app.tasks.expand.expand_from_forwards",
    max_retries=1,
    default_retry_delay=300,
)
def expand_from_forwards(self) -> dict:
    """Daily: top-50 most-forwarded chat_ids from recent messages."""

    async def _run() -> dict:
        from collections import Counter

        from sqlalchemy import text

        from app.core.config import get_settings
        from app.core.database import AsyncSessionLocal, dispose_engine
        from app.parser.client import TelethonClient

        await dispose_engine()
        settings = get_settings()
        min_members = settings.EXPAND_MIN_MEMBERS

        user_id = await _resolve_owner(settings)
        if user_id is None:
            return {"error": "owner_not_found"}

        async with AsyncSessionLocal() as db:
            try:
                rows = await db.execute(
                    text(
                        "SELECT forward_from_chat_id FROM messages "
                        "WHERE forward_from_chat_id IS NOT NULL "
                        "ORDER BY id DESC LIMIT 5000"
                    )
                )
                chat_ids = [r[0] for r in rows.fetchall()]
            except Exception as exc:
                logger.warning(
                    "expand_from_forwards: forward_from_chat_id column unavailable: %s", exc
                )
                return {"skipped": "forward_from_chat_id_missing"}

        if not chat_ids:
            logger.info("expand_from_forwards: no forwarded messages found")
            return {"added": 0, "skipped": "no_data"}

        counter: Counter = Counter(chat_ids)
        top_ids = [cid for cid, _ in counter.most_common(50)]

        candidates: list[dict] = []
        rejected_items: list[dict] = []
        checked = rejected_private = rejected_small = rejected_not_group = 0

        async with TelethonClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        ) as client:
            for chat_id in top_ids:
                checked += 1
                try:
                    entity = await client._client.get_entity(int(chat_id))
                    username = getattr(entity, "username", None)
                    members = getattr(entity, "participants_count", None)
                    if not username:
                        rejected_private += 1
                        continue
                    if members is not None and members < min_members:
                        rejected_small += 1
                        rejected_items.append({
                            "url": f"@{username}",
                            "name": getattr(entity, "title", username),
                            "reason": "too_small",
                            "member_count": members or 0,
                            "discovery_method": "expand_forwards",
                        })
                        continue
                    if not _is_group(entity):
                        rejected_not_group += 1
                        rejected_items.append({
                            "url": f"@{username}",
                            "name": getattr(entity, "title", username),
                            "reason": "broadcast",
                            "member_count": members or 0,
                            "discovery_method": "expand_forwards",
                        })
                        continue
                    candidates.append(
                        {"url": f"@{username}", "name": getattr(entity, "title", username)}
                    )
                    await asyncio.sleep(random.uniform(1, 3))
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 10)
                except Exception as exc:
                    logger.debug("expand_from_forwards entity error %d: %s", chat_id, exc)

        ins = await _bulk_insert(candidates, user_id, "expand_forwards", min_members)
        await _bulk_insert_rejected(rejected_items)
        stats = {
            "top_ids_checked": checked,
            "added": ins["added"],
            "already_exists": ins["already_exists"],
            "rejected_private": rejected_private,
            "rejected_small": rejected_small,
            "rejected_not_group": rejected_not_group,
        }
        logger.info("expand_from_forwards done: %s", stats)
        await _notify(
            settings,
            f"↩️ Расширение: форварды\n"
            f"Топ чатов проверено: {checked}\n"
            f"Добавлено: {ins['added']} · уже было: {ins['already_exists']}\n"
            f"Откл.: приватных {rejected_private}, маленьких {rejected_small}, "
            f"не группа {rejected_not_group}",
        )
        return stats

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("expand_from_forwards failed: %s", exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Task 3 — Mentions
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="app.tasks.expand.expand_from_mentions",
    max_retries=1,
    default_retry_delay=300,
)
def expand_from_mentions(self) -> dict:
    """Daily: regex @usernames in recent messages, check top-50."""

    async def _run() -> dict:
        from collections import Counter

        from sqlalchemy import select

        from app.core.config import get_settings
        from app.core.database import AsyncSessionLocal, dispose_engine
        from app.models.message import Message
        from app.parser.client import TelethonClient

        await dispose_engine()
        settings = get_settings()
        min_members = settings.EXPAND_MIN_MEMBERS

        user_id = await _resolve_owner(settings)
        if user_id is None:
            return {"error": "owner_not_found"}

        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(Message.text)
                .where(Message.text.isnot(None))
                .order_by(Message.id.desc())
                .limit(10000)
            )
            texts = [r[0] for r in rows.fetchall()]

        counter: Counter = Counter()
        for t in texts:
            for m in _USERNAME_RE.finditer(t):
                counter[m.group(1).lower()] += 1

        top_usernames = [u for u, _ in counter.most_common(50)]

        candidates: list[dict] = []
        rejected_items: list[dict] = []
        checked = rejected_private = rejected_small = rejected_not_group = 0

        async with TelethonClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        ) as client:
            for username in top_usernames:
                checked += 1
                try:
                    entity = await client._client.get_entity(f"@{username}")
                    real_username = getattr(entity, "username", None)
                    members = getattr(entity, "participants_count", None)
                    if not real_username:
                        rejected_private += 1
                        continue
                    if members is not None and members < min_members:
                        rejected_small += 1
                        rejected_items.append({
                            "url": f"@{real_username}",
                            "name": getattr(entity, "title", real_username),
                            "reason": "too_small",
                            "member_count": members or 0,
                            "discovery_method": "expand_mentions",
                        })
                        continue
                    if not _is_group(entity):
                        rejected_not_group += 1
                        rejected_items.append({
                            "url": f"@{real_username}",
                            "name": getattr(entity, "title", real_username),
                            "reason": "broadcast",
                            "member_count": members or 0,
                            "discovery_method": "expand_mentions",
                        })
                        continue
                    candidates.append(
                        {
                            "url": f"@{real_username}",
                            "name": getattr(entity, "title", real_username),
                        }
                    )
                    await asyncio.sleep(random.uniform(1, 3))
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 10)
                except Exception as exc:
                    logger.debug("expand_from_mentions entity error @%s: %s", username, exc)

        ins = await _bulk_insert(candidates, user_id, "expand_mentions", min_members)
        await _bulk_insert_rejected(rejected_items)
        stats = {
            "texts_scanned": len(texts),
            "unique_usernames_found": len(counter),
            "checked": checked,
            "added": ins["added"],
            "already_exists": ins["already_exists"],
            "rejected_private": rejected_private,
            "rejected_small": rejected_small,
            "rejected_not_group": rejected_not_group,
        }
        logger.info("expand_from_mentions done: %s", stats)
        await _notify(
            settings,
            f"💬 Расширение: упоминания\n"
            f"Текстов: {len(texts)} · уник. @username: {len(counter)}\n"
            f"Проверено топ-{checked}: {checked}\n"
            f"Добавлено: {ins['added']} · уже было: {ins['already_exists']}\n"
            f"Откл.: приватных {rejected_private}, маленьких {rejected_small}, "
            f"не группа {rejected_not_group}",
        )
        return stats

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("expand_from_mentions failed: %s", exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Task 4 — Global keyword search
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="app.tasks.expand.expand_from_search",
    max_retries=1,
    default_retry_delay=300,
)
def expand_from_search(self) -> dict:
    """Every N days: global search with random POSITIVE_KEYWORDS sample."""

    async def _run() -> dict:
        from app.core.config import get_settings
        from app.core.database import AsyncSessionLocal, dispose_engine
        from app.parser.client import TelethonClient
        from app.repositories.source import SourceRepository
        from app.scoring.keyword_filter import POSITIVE_KEYWORDS

        await dispose_engine()
        settings = get_settings()
        min_members = settings.EXPAND_MIN_MEMBERS

        user_id = await _resolve_owner(settings)
        if user_id is None:
            return {"error": "owner_not_found"}

        async with AsyncSessionLocal() as db:
            warm_sources = await SourceRepository.get_all_active(db, user_id=user_id)

        n = min(10, len(POSITIVE_KEYWORDS))
        keywords = random.sample(POSITIVE_KEYWORDS, n)

        candidates: list[dict] = []
        rejected_items: list[dict] = []
        checked = rejected_private = rejected_small = 0

        async with TelethonClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        ) as client:
            # Warm up the session by resolving known entities — search_global returns
            # 0 results on a cold session that hasn't resolved any peers yet.
            for src in warm_sources[:5]:
                try:
                    await client._client.get_entity(src.url)
                    logger.debug("expand_from_search: warmed up session with %s", src.url)
                except Exception as exc:
                    logger.debug("expand_from_search: warmup skip %s: %s", src.url, exc)
            if warm_sources:
                await asyncio.sleep(2)

            for keyword in keywords:
                try:
                    results = await client.search_global_messages(keyword, limit=20)
                    for r in results:
                        checked += 1
                        logger.debug(
                            "expand_from_search: found msg chat=@%s text=%r",
                            r.chat_username,
                            (r.message_text or "")[:120],
                        )
                        if not r.chat_username:
                            rejected_private += 1
                            continue
                        if r.chat_members is not None and r.chat_members < min_members:
                            rejected_small += 1
                            rejected_items.append({
                                "url": f"@{r.chat_username}",
                                "name": r.chat_title or r.chat_username,
                                "reason": "too_small",
                                "member_count": r.chat_members or 0,
                                "discovery_method": "expand_search",
                            })
                            continue
                        candidates.append(
                            {
                                "url": f"@{r.chat_username}",
                                "name": r.chat_title or r.chat_username,
                            }
                        )
                    await asyncio.sleep(random.uniform(10, 20))
                except FloodWaitError as e:
                    wait = e.seconds + 10
                    logger.warning("expand_from_search FloodWait %ds for %r", wait, keyword)
                    await asyncio.sleep(wait)
                except Exception as exc:
                    logger.error("expand_from_search error for %r: %s", keyword, exc)

        ins = await _bulk_insert(candidates, user_id, "expand_search", min_members)
        await _bulk_insert_rejected(rejected_items)
        stats = {
            "keywords_used": len(keywords),
            "candidates_checked": checked,
            "added": ins["added"],
            "already_exists": ins["already_exists"],
            "rejected_private": rejected_private,
            "rejected_small": rejected_small,
        }
        logger.info("expand_from_search done: %s", stats)
        await _notify(
            settings,
            f"🔎 Расширение: поиск\n"
            f"Ключевых слов: {len(keywords)} · кандидатов: {checked}\n"
            f"Добавлено: {ins['added']} · уже было: {ins['already_exists']}\n"
            f"Откл.: приватных {rejected_private}, маленьких {rejected_small}",
        )
        return stats

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("expand_from_search failed: %s", exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Task 5 — tgstat.ru scraping
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="app.tasks.expand.expand_from_tgstat",
    max_retries=1,
    default_retry_delay=300,
)
def expand_from_tgstat(self) -> dict:
    """Monthly: Google search for tgstat.ru/en/chat links, verify candidates via Telethon."""

    async def _run() -> dict:
        import urllib.parse

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("expand_from_tgstat: beautifulsoup4 not installed")
            return {"error": "bs4_not_installed"}

        from app.core.config import get_settings
        from app.core.database import dispose_engine
        from app.parser.client import TelethonClient

        await dispose_engine()
        settings = get_settings()
        min_members = settings.EXPAND_MIN_MEMBERS

        user_id = await _resolve_owner(settings)
        if user_id is None:
            return {"error": "owner_not_found"}

        proxy = settings.PROXY_URL or None
        headers = {"User-Agent": _GOOGLE_UA}
        raw_usernames: set[str] = set()
        queries_ok = queries_blocked = 0

        async with httpx.AsyncClient(
            timeout=30, proxy=proxy, headers=headers, follow_redirects=True
        ) as http:
            for query in _GOOGLE_TGSTAT_QUERIES:
                gurl = f"https://www.google.com/search?q={urllib.parse.quote(query)}&num=10"
                try:
                    resp = await http.get(gurl)
                    if resp.status_code == 429 or "/sorry/" in str(resp.url):
                        logger.warning(
                            "expand_from_tgstat: Google rate-limited (429/captcha) — stopping"
                        )
                        queries_blocked += 1
                        break
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, "html.parser")
                    found_before = len(raw_usernames)
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if href.startswith("/url?"):
                            parsed_qs = urllib.parse.parse_qs(
                                urllib.parse.urlparse(href).query
                            )
                            href = parsed_qs.get("q", [""])[0]
                        m = _TGSTAT_CHAT_RE.search(href)
                        if m:
                            raw_usernames.add(m.group(1).lower())
                    queries_ok += 1
                    logger.info(
                        "expand_from_tgstat: query %r → +%d usernames (total %d)",
                        query,
                        len(raw_usernames) - found_before,
                        len(raw_usernames),
                    )
                    await asyncio.sleep(random.uniform(3, 7))
                except httpx.HTTPStatusError as exc:
                    logger.warning("expand_from_tgstat HTTP error for %r: %s", query, exc)
                except Exception as exc:
                    logger.error("expand_from_tgstat error for %r: %s", query, exc)

        if not raw_usernames:
            stats = {
                "queries_ok": queries_ok,
                "queries_blocked": queries_blocked,
                "added": 0,
            }
            logger.info("expand_from_tgstat: no usernames found — %s", stats)
            return stats

        candidates: list[dict] = []
        rejected_items: list[dict] = []
        checked = rejected_private = rejected_small = rejected_not_group = 0

        async with TelethonClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        ) as client:
            for username in raw_usernames:
                checked += 1
                try:
                    entity = await client._client.get_entity(f"@{username}")
                    real_username = getattr(entity, "username", None)
                    members = getattr(entity, "participants_count", None)
                    if not real_username:
                        rejected_private += 1
                        continue
                    if members is not None and members < min_members:
                        rejected_small += 1
                        rejected_items.append({
                            "url": f"@{real_username}",
                            "name": getattr(entity, "title", real_username),
                            "reason": "too_small",
                            "member_count": members or 0,
                            "discovery_method": "expand_tgstat",
                        })
                        continue
                    if not _is_group(entity):
                        rejected_not_group += 1
                        rejected_items.append({
                            "url": f"@{real_username}",
                            "name": getattr(entity, "title", real_username),
                            "reason": "broadcast",
                            "member_count": members or 0,
                            "discovery_method": "expand_tgstat",
                        })
                        continue
                    candidates.append(
                        {
                            "url": f"@{real_username}",
                            "name": getattr(entity, "title", real_username),
                        }
                    )
                    await asyncio.sleep(random.uniform(1, 3))
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 10)
                except Exception as exc:
                    logger.debug("expand_from_tgstat entity error @%s: %s", username, exc)

        ins = await _bulk_insert(candidates, user_id, "expand_tgstat", min_members)
        await _bulk_insert_rejected(rejected_items)
        stats = {
            "queries_ok": queries_ok,
            "queries_blocked": queries_blocked,
            "usernames_found": len(raw_usernames),
            "checked": checked,
            "added": ins["added"],
            "already_exists": ins["already_exists"],
            "rejected_private": rejected_private,
            "rejected_small": rejected_small,
            "rejected_not_group": rejected_not_group,
        }
        logger.info("expand_from_tgstat done: %s", stats)
        await _notify(
            settings,
            f"📊 Расширение: tgstat (Google)\n"
            f"Запросов: {queries_ok} · заблокировано: {queries_blocked}\n"
            f"Найдено username: {len(raw_usernames)} · проверено: {checked}\n"
            f"Добавлено: {ins['added']} · уже было: {ins['already_exists']}\n"
            f"Откл.: приватных {rejected_private}, маленьких {rejected_small}, "
            f"не группа {rejected_not_group}",
        )
        return stats

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("expand_from_tgstat failed: %s", exc)
        raise self.retry(exc=exc)
