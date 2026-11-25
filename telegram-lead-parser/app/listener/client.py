import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import FloodWaitError, UserDeactivatedError, PeerIdInvalidError

from app.listener.schemas import RawMessage

logger = logging.getLogger(__name__)

_FLOOD_PAUSE_BUFFER = 5
_PROFILE_PAUSE = 1.0

MessageHandler = Callable[[RawMessage], Coroutine[Any, Any, None]]


class ListenerClient:
    """
    Wraps a Telethon client in persistent event-listener mode.
    Subscribes to a dynamic set of source URLs and calls `on_message`
    for every new text message.
    """

    def __init__(
        self, api_id: int, api_hash: str, session_string: str, proxy: tuple | None = None
    ) -> None:
        if proxy is None:
            from app.core.config import get_settings
            proxy = get_settings().telethon_proxy
        session = StringSession(session_string)
        self._client = TelegramClient(session, api_id, api_hash, proxy=proxy)
        if proxy:
            logger.info("ListenerClient using proxy %s:%s", proxy[1], proxy[2])
        self._sources: dict[str, int] = {}  # url -> source_id
        self._on_message: MessageHandler | None = None

    def set_handler(self, handler: MessageHandler) -> None:
        self._on_message = handler

    def add_source(self, url: str, source_id: int) -> None:
        self._sources[url] = source_id
        logger.info("ListenerClient: added source url=%s id=%d", url, source_id)

    def remove_source(self, url: str) -> None:
        self._sources.pop(url, None)
        logger.info("ListenerClient: removed source url=%s", url)

    @property
    def source_urls(self) -> set[str]:
        return set(self._sources.keys())

    async def get_user_bio(self, user_id: int) -> str | None:
        try:
            full = await self._client(GetFullUserRequest(user_id))
            return full.full_user.about
        except (UserDeactivatedError, PeerIdInvalidError):
            return None
        except FloodWaitError as e:
            wait = e.seconds + _FLOOD_PAUSE_BUFFER
            logger.warning("FloodWaitError fetching bio, waiting %ds", wait)
            await asyncio.sleep(wait)
            return None
        except Exception as exc:
            logger.debug("Could not fetch bio for user_id=%d: %s", user_id, exc)
            return None

    async def connect(self) -> None:
        await self._client.connect()
        logger.info("ListenerClient connected to Telegram")

    async def disconnect(self) -> None:
        await self._client.disconnect()
        logger.info("ListenerClient disconnected")

    async def _handle_new_message(self, event: events.NewMessage.Event) -> None:
        if not self._on_message:
            return

        msg = event.message
        if not msg or not msg.message:
            return

        # Determine which source this message belongs to
        chat = await event.get_chat()
        chat_username = getattr(chat, "username", None)
        if not chat_username:
            return

        # Normalize to @username format
        source_url = f"@{chat_username}"
        if source_url not in self._sources:
            return

        sender = await event.get_sender()
        sender_name = ""
        sender_username = None
        sender_id = msg.sender_id

        if sender:
            first = getattr(sender, "first_name", "") or ""
            last = getattr(sender, "last_name", "") or ""
            sender_name = f"{first} {last}".strip()
            sender_username = getattr(sender, "username", None)

        # Fetch bio with rate limit pause
        sender_bio: str | None = None
        if sender_id:
            await asyncio.sleep(_PROFILE_PAUSE)
            sender_bio = await self.get_user_bio(sender_id)

        forward_from_chat_id: int | None = None
        if msg.fwd_from and msg.fwd_from.from_id:
            from telethon.tl.types import PeerChannel, PeerChat
            fwd = msg.fwd_from.from_id
            if isinstance(fwd, PeerChannel):
                forward_from_chat_id = fwd.channel_id
            elif isinstance(fwd, PeerChat):
                forward_from_chat_id = fwd.chat_id

        raw = RawMessage(
            tg_message_id=msg.id,
            source_url=source_url,
            text=msg.message,
            tg_date=msg.date,
            sender_id=sender_id,
            sender_name=sender_name,
            sender_username=sender_username,
            sender_bio=sender_bio,
            forward_from_chat_id=forward_from_chat_id,
        )

        try:
            await self._on_message(raw)
        except Exception as exc:
            logger.error("Handler error for message tg_id=%d: %s", msg.id, exc)

    async def start_listening(self) -> None:
        """Register event handler and run until disconnected."""
        self._client.add_event_handler(
            self._handle_new_message,
            events.NewMessage(incoming=True),
        )
        logger.info(
            "ListenerClient: listening on %d sources", len(self._sources)
        )
        await self._client.run_until_disconnected()
