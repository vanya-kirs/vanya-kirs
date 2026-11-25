import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.core.database import AsyncSessionLocal
from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        start = time.monotonic()

        user = data.get("event_from_user")
        user_info = f"user_id={user.id} @{user.username}" if user else "unknown"

        update: Update | None = data.get("update")
        event_type = "unknown"
        event_content = ""
        if update:
            if update.message:
                event_type = "message"
                event_content = update.message.text or update.message.caption or ""
            elif update.callback_query:
                event_type = "callback"
                event_content = update.callback_query.data or ""

        logger.info(
            "Update [%s] from %s: %r",
            event_type,
            user_info,
            event_content[:100],
        )

        result = await handler(event, data)

        duration_ms = (time.monotonic() - start) * 1000
        logger.debug("Handled [%s] from %s in %.1fms", event_type, user_info, duration_ms)
        return result


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user:
            async with AsyncSessionLocal() as db:
                db_user = await UserRepository.get_or_create_telegram(
                    db,
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                )
            data["db_user"] = db_user
        return await handler(event, data)
