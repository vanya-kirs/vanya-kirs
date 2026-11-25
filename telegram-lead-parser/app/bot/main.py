import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.api_client import BotApiClient
from app.bot.handlers import admin, leads, profile, start
from app.bot.middleware import LoggingMiddleware, UserMiddleware
from app.bot.texts import BOT_STARTED
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
RECONNECT_DELAY_SECONDS = 5


async def main() -> None:
    settings = get_settings()

    proxy_url = settings.PROXY_URL or None
    bot_session = AiohttpSession(proxy=proxy_url) if proxy_url else None
    bot = Bot(
        token=settings.BOT_TOKEN,
        session=bot_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    storage = RedisStorage.from_url(settings.REDIS_URL)
    dp = Dispatcher(storage=storage)

    # Shared API client — injected into handlers via middleware data
    api_client = BotApiClient()

    # Middleware
    dp.update.outer_middleware(LoggingMiddleware())
    dp.update.outer_middleware(UserMiddleware())

    # Inject api_client into handler data
    dp["api"] = api_client

    # Routers
    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(admin.router)
    dp.include_router(leads.router)

    # Notify owner on startup
    if settings.OWNER_TELEGRAM_ID:
        try:
            await bot.send_message(settings.OWNER_TELEGRAM_ID, BOT_STARTED)
        except Exception as exc:
            logger.warning("Could not notify owner on startup: %s", exc)

    logger.info("Starting bot polling...")
    try:
        while True:
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
                break
            except TelegramNetworkError as exc:
                logger.warning(
                    "Telegram network error during polling: %s. Retrying in %s seconds...",
                    exc,
                    RECONNECT_DELAY_SECONDS,
                )
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
    finally:
        await api_client.close()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
