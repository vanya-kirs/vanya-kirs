import logging

from aiogram import Bot

from app.bot.keyboards import lead_actions_kb
from app.bot.utils import format_lead_card
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _admin_targets(settings) -> list[int]:
    """All admin IDs, falling back to OWNER_TELEGRAM_ID if ADMIN_IDS is empty."""
    targets = list(settings.admin_ids)
    if not targets and settings.OWNER_TELEGRAM_ID:
        targets = [settings.OWNER_TELEGRAM_ID]
    return targets


async def send_channel_renamed_notification(
    bot: Bot, source_name: str, old_url: str, new_url: str
) -> None:
    """Notify all admins that a channel changed its username; parsing resumed with new URL."""
    settings = get_settings()
    targets = _admin_targets(settings)
    if not targets:
        return
    text = (
        f"🔄 Канал сменил ссылку\n\n"
        f"Источник: {source_name}\n"
        f"Старая ссылка: {old_url}\n"
        f"Новая ссылка: {new_url}\n\n"
        f"Парсинг продолжен с новой ссылкой."
    )
    for chat_id in targets:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception as exc:
            logger.error("Failed to send channel rename notification to %d: %s", chat_id, exc)
    logger.info("Channel rename notification sent for source %r", source_name)


async def send_channel_lost_notification(
    bot: Bot, source_name: str, old_url: str, tg_channel_id: int | None
) -> None:
    """Notify all admins that a channel could not be found and source was deactivated."""
    settings = get_settings()
    targets = _admin_targets(settings)
    if not targets:
        return
    id_line = f"Telegram ID: {tg_channel_id}" if tg_channel_id else "Telegram ID неизвестен"
    text = (
        f"❌ Канал недоступен — источник деактивирован\n\n"
        f"Источник: {source_name}\n"
        f"Ссылка: {old_url}\n"
        f"{id_line}"
    )
    for chat_id in targets:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception as exc:
            logger.error("Failed to send channel lost notification to %d: %s", chat_id, exc)
    logger.info("Channel lost notification sent for source %r", source_name)


async def send_lead_notification(bot: Bot, lead_data: dict) -> None:
    """Send lead card to OWNER_TELEGRAM_ID. Called from Celery tasks."""
    settings = get_settings()
    owner_id = settings.OWNER_TELEGRAM_ID
    if not owner_id:
        logger.warning("OWNER_TELEGRAM_ID not set — skipping lead notification")
        return

    lead_id = lead_data.get("id")
    if not lead_id:
        logger.warning("send_lead_notification: lead_data has no id, skipping")
        return

    text = format_lead_card(lead_data)

    try:
        await bot.send_message(
            chat_id=owner_id,
            text=text,
            reply_markup=lead_actions_kb(lead_id),
        )
        logger.info("Lead notification sent to owner for lead_id=%s", lead_id)
    except Exception as exc:
        logger.error("Failed to send lead notification: %s", exc)
