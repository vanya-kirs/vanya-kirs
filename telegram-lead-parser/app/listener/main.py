import asyncio
import logging
import signal

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.listener.service import ListenerService

setup_logging(enable_listener_file=True)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()

    if not settings.OWNER_TELEGRAM_ID:
        logger.error("OWNER_TELEGRAM_ID is not set — cannot start listener")
        return

    service = ListenerService(user_id=settings.OWNER_TELEGRAM_ID)

    loop = asyncio.get_running_loop()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("Received %s — stopping listener", sig.name)
        service.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    await service.start()


if __name__ == "__main__":
    asyncio.run(main())
