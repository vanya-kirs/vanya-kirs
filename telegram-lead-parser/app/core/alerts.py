"""Lightweight admin alert sender — uses raw httpx so it works from any context
(Celery worker, scoring service, etc.) without importing aiogram."""
import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 10


async def notify_admin(text: str) -> None:
    """Send a plain-text message to all admin Telegram IDs defined in settings."""
    from app.core.config import get_settings
    settings = get_settings()

    token = settings.BOT_TOKEN
    if not token:
        logger.warning("notify_admin: BOT_TOKEN not set, skipping alert")
        return

    admin_ids = settings.admin_ids or (
        [settings.OWNER_TELEGRAM_ID] if settings.OWNER_TELEGRAM_ID else []
    )
    if not admin_ids:
        logger.warning("notify_admin: no admin IDs configured, skipping alert")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    proxy = settings.PROXY_URL or None

    async with httpx.AsyncClient(timeout=_TIMEOUT, proxy=proxy) as client:
        for admin_id in admin_ids:
            try:
                resp = await client.post(url, json={
                    "chat_id": admin_id,
                    "text": text,
                    "parse_mode": "HTML",
                })
                if not resp.is_success:
                    logger.warning(
                        "notify_admin: Telegram returned %d for admin_id=%s: %s",
                        resp.status_code, admin_id, resp.text[:200],
                    )
            except Exception as exc:
                logger.error("notify_admin: failed to send to admin_id=%s: %s", admin_id, exc)
