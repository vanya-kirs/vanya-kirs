import asyncio
import logging

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.listener.client import ListenerClient
from app.listener.health import ListenerHealthCheck
from app.listener.processor import MessageProcessor
from app.listener.schemas import RawMessage
from app.listener.sync import SourceSyncSubscriber
from app.repositories.source import SourceRepository

logger = logging.getLogger(__name__)

_RESTART_DELAY = 10  # seconds before auto-restart after crash


class ListenerService:
    """
    Top-level orchestrator for the real-time listener.
    - Loads active sources from DB on startup
    - Starts ListenerClient with Telethon event handler
    - Subscribes to Redis for new-source notifications
    - Runs ListenerHealthCheck heartbeats
    - Auto-restarts the Telethon client on disconnection
    """

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id
        settings = get_settings()
        self._settings = settings

        # Shared source map: url -> source_id (mutated by sync subscriber)
        self._source_map: dict[str, int] = {}

        self._client = ListenerClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        )
        self._processor = MessageProcessor(self._source_map)
        self._health = ListenerHealthCheck(settings.REDIS_URL)
        self._sync_sub = SourceSyncSubscriber(
            redis_url=settings.REDIS_URL,
            on_source_added=self._on_source_added,
        )
        self._stop_event = asyncio.Event()

    async def _load_sources(self) -> None:
        """Pull active sources from DB and populate source_map + client."""
        async with AsyncSessionLocal() as db:
            sources = await SourceRepository.get_all_active(db, user_id=self._user_id)

        self._source_map.clear()
        for src in sources:
            self._source_map[src.url] = src.id
            self._client.add_source(src.url, src.id)

        logger.info(
            "ListenerService: loaded %d sources for user_id=%d",
            len(sources),
            self._user_id,
        )

    async def _on_source_added(self, source_id: int, url: str, user_id: int) -> None:
        """Called by SourceSyncSubscriber when a new source is published."""
        if user_id != self._user_id:
            return
        self._source_map[url] = source_id
        self._client.add_source(url, source_id)
        logger.info(
            "ListenerService: dynamically added source_id=%d url=%s", source_id, url
        )

    async def _message_handler(self, raw: RawMessage) -> None:
        async with AsyncSessionLocal() as db:
            await self._processor.process(db, raw, self._user_id)

    async def start(self) -> None:
        logger.info("ListenerService: starting for user_id=%d", self._user_id)

        await self._load_sources()
        self._client.set_handler(self._message_handler)

        self._health.start()
        self._sync_sub.start()

        while not self._stop_event.is_set():
            try:
                await self._client.connect()
                logger.info("ListenerService: client connected, entering event loop")
                await self._client.start_listening()
            except asyncio.CancelledError:
                logger.info("ListenerService: cancelled")
                break
            except Exception as exc:
                logger.error(
                    "ListenerService: client crashed: %s — restarting in %ds",
                    exc,
                    _RESTART_DELAY,
                )
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(_RESTART_DELAY)

        await self._shutdown()

    async def _shutdown(self) -> None:
        self._health.stop()
        self._sync_sub.stop()
        try:
            await self._client.disconnect()
        except Exception:
            pass
        logger.info("ListenerService: shutdown complete")

    def stop(self) -> None:
        self._stop_event.set()
