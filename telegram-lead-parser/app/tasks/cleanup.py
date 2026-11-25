import asyncio
import csv
import io
import logging

import httpx

from app.core.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.repositories.lead import LeadRepository

logger = logging.getLogger(__name__)


def _send_text_sync(bot_token: str, chat_id: int, text: str, proxy: str | None = None) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    with httpx.Client(timeout=10, proxy=proxy) as client:
        client.post(url, json={"chat_id": chat_id, "text": text})


@celery_app.task(name="app.tasks.cleanup.cleanup_expired_leads")
def cleanup_expired_leads() -> dict:
    """Delete new/viewed/rejected leads older than 2 days."""
    async def _run() -> int:
        from app.core.database import dispose_engine
        await dispose_engine()
        async with AsyncSessionLocal() as db:
            return await LeadRepository.delete_old_inactive(db)

    deleted = asyncio.run(_run())
    logger.info("cleanup_expired_leads: deleted=%d", deleted)
    return {"deleted": deleted}


@celery_app.task(name="app.tasks.cleanup.send_parse_digest")
def send_parse_digest() -> dict:
    """Send a daily parsing digest to all admins (runs 4× per day)."""
    from app.core.config import get_settings
    from app.core.database import dispose_engine
    from app.repositories.message import MessageRepository
    from app.repositories.source import SourceRepository

    settings = get_settings()
    targets: list[int] = list(settings.admin_ids)
    if not targets and settings.OWNER_TELEGRAM_ID:
        targets = [settings.OWNER_TELEGRAM_ID]
    if not targets:
        return {"skipped": "no_admins"}

    async def _collect() -> dict:
        await dispose_engine()
        async with AsyncSessionLocal() as db:
            # Find the owner user_id (first active user; bot-only setup has one user)
            from app.models.user import User
            from sqlalchemy import select
            row = (await db.execute(select(User).where(User.is_active == True).limit(1))).scalar_one_or_none()  # noqa: E712
            if row is None:
                return {}
            uid = row.id
            messages_today = await MessageRepository.count_today(db, uid)
            scored_today = await MessageRepository.count_scored_today(db, uid)
            leads_today = await LeadRepository.count_today(db, uid)
            source_stats = await SourceRepository.get_stats_per_source(db, uid)
            return {
                "messages_today": messages_today,
                "scored_today": scored_today,
                "leads_today": leads_today,
                "source_stats": source_stats,
            }

    data = asyncio.run(_collect())
    if not data:
        logger.info("send_parse_digest: no users found, skipping")
        return {"skipped": "no_users"}

    active_sources = [
        s for s in data.get("source_stats", [])
        if s.get("messages_today", 0) > 0 or s.get("leads_today", 0) > 0
    ]
    active_sources.sort(key=lambda x: x.get("leads_today", 0), reverse=True)

    lines = []
    for s in active_sources[:10]:
        lines.append(
            f"• {s['name']}: постов {s['messages_today']}, "
            f"ИИ {s['scored_today']}, лидов {s['leads_today']}"
        )

    sources_part = "\n".join(lines) if lines else "Нет активности за сегодня"

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    text = (
        f"Итог парсинга ({now}):\n\n"
        f"Постов сегодня: {data['messages_today']}\n"
        f"Дошло до ИИ: {data['scored_today']}\n"
        f"Лидов найдено: {data['leads_today']}\n\n"
        f"По каналам:\n{sources_part}"
    )

    proxy = settings.PROXY_URL or None
    for admin_id in targets:
        try:
            _send_text_sync(settings.BOT_TOKEN, admin_id, text, proxy=proxy)
        except Exception as exc:
            logger.error("send_parse_digest: failed to notify admin %d: %s", admin_id, exc)

    logger.info(
        "send_parse_digest: messages=%d scored=%d leads=%d admins=%d",
        data["messages_today"], data["scored_today"], data["leads_today"], len(targets),
    )
    return {
        "messages_today": data["messages_today"],
        "leads_today": data["leads_today"],
    }


def _build_skipped_csv(messages: list) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "source_id", "причина", "текст", "дата"])
    for msg in messages:
        writer.writerow([
            msg.id,
            msg.source_id,
            msg.score_skip_reason or "",
            (msg.text or "")[:500],
            msg.tg_date.isoformat() if msg.tg_date else "",
        ])
    out.seek(0)
    return out.getvalue().encode("utf-8-sig")


def _send_document_sync(
    bot_token: str, chat_id: int, data: bytes, filename: str, caption: str, proxy: str | None = None
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    with httpx.Client(timeout=30, proxy=proxy) as client:
        client.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (filename, data, "text/csv")},
        )


@celery_app.task(name="app.tasks.cleanup.export_skipped_messages")
def export_skipped_messages() -> dict:
    """At 22:00: export pre-filtered + AI-rejected messages to admins, then clear skip reasons."""
    from app.core.config import get_settings
    from app.core.database import dispose_engine
    from app.repositories.message import MessageRepository

    settings = get_settings()

    async def _collect() -> list:
        await dispose_engine()
        async with AsyncSessionLocal() as db:
            return await MessageRepository.get_all_skipped_for_export(db)

    async def _clear() -> int:
        await dispose_engine()
        async with AsyncSessionLocal() as db:
            return await MessageRepository.clear_all_skip_reasons(db)

    messages = asyncio.run(_collect())

    if not messages:
        logger.info("export_skipped_messages: nothing to export")
        return {"exported": 0}

    pre_filtered = [m for m in messages if m.score_skip_reason == "pre_filtered"]
    ai_rejected = [m for m in messages if m.score_skip_reason == "ai_rejected"]

    logger.info(
        "export_skipped_messages: pre_filtered=%d ai_rejected=%d admins=%s",
        len(pre_filtered), len(ai_rejected), settings.admin_ids,
    )

    proxy = settings.PROXY_URL or None
    for admin_id in settings.admin_ids:
        try:
            if pre_filtered:
                data = _build_skipped_csv(pre_filtered)
                _send_document_sync(
                    settings.BOT_TOKEN, admin_id, data,
                    "pre_filtered.csv",
                    f"Не дошли до ИИ: {len(pre_filtered)} сообщений",
                    proxy=proxy,
                )
            if ai_rejected:
                data = _build_skipped_csv(ai_rejected)
                _send_document_sync(
                    settings.BOT_TOKEN, admin_id, data,
                    "ai_rejected.csv",
                    f"Отклонены ИИ: {len(ai_rejected)} сообщений",
                    proxy=proxy,
                )
        except Exception as exc:
            logger.error("export_skipped_messages: failed to notify admin %d: %s", admin_id, exc)

    cleared = asyncio.run(_clear())
    logger.info("export_skipped_messages: cleared=%d skip_reason fields", cleared)
    return {"exported": len(messages), "cleared": cleared}
