import asyncio
import logging
import random
from datetime import datetime

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    PeerIdInvalidError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.users import GetFullUserRequest

from app.parser.exceptions import BannedError
from app.parser.schemas import GlobalSearchResult, MessageData, SourceValidation, UserProfile

logger = logging.getLogger(__name__)

_FLOOD_PAUSE_BUFFER = 10
_PROFILE_PAUSE = 1.0


class TelethonClient:
    def __init__(
        self, api_id: int, api_hash: str, session_string: str, proxy: tuple | None = None
    ) -> None:
        if proxy is None:
            from app.core.config import get_settings
            proxy = get_settings().telethon_proxy
        try:
            session = StringSession(session_string)
        except ValueError:
            session = StringSession("")
        self._client = TelegramClient(session, api_id, api_hash, proxy=proxy, receive_updates=False)
        if proxy:
            logger.info("TelethonClient using proxy %s:%s", proxy[1], proxy[2])

    async def connect(self) -> None:
        await self._client.connect()
        logger.info("Telethon connected")

    async def disconnect(self) -> None:
        await self._client.disconnect()
        logger.info("Telethon disconnected")

    async def __aenter__(self) -> "TelethonClient":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()

    async def join_channel(self, source_url: str) -> None:
        logger.info("[JOIN] joining %s", source_url)
        try:
            await self._client(JoinChannelRequest(channel=source_url))
        except UserDeactivatedBanError:
            logger.critical("[BAN] UserDeactivatedBanError — stopping")
            raise BannedError("Account banned by Telegram")
        except FloodWaitError as e:
            wait = e.seconds + _FLOOD_PAUSE_BUFFER
            logger.warning("[FLOOD] waiting %ds (%d+10)", wait, e.seconds)
            await asyncio.sleep(wait)
            raise

    async def scrape_messages(
        self,
        source_url: str,
        limit: int = 200,
        min_id: int = 0,
        offset_date: datetime | None = None,
    ) -> list[MessageData]:
        results: list[MessageData] = []
        kwargs: dict = {"limit": limit, "min_id": min_id}

        try:
            async for msg in self._client.iter_messages(source_url, **kwargs):
                # Stop iterating once we pass the date cutoff (messages arrive newest-first)
                if offset_date is not None and msg.date < offset_date:
                    break

                pause = random.uniform(3.0, 8.0)
                logger.debug("[RATE] msg pause %.1fs", pause)
                await asyncio.sleep(pause)

                if not msg.message:
                    continue

                sender = msg.sender
                sender_name = ""
                sender_username = None
                if sender:
                    first = getattr(sender, "first_name", "") or ""
                    last = getattr(sender, "last_name", "") or ""
                    sender_name = f"{first} {last}".strip()
                    sender_username = getattr(sender, "username", None)

                forward_from_chat_id: int | None = None
                if msg.fwd_from and msg.fwd_from.from_id:
                    from telethon.tl.types import PeerChannel, PeerChat
                    fwd = msg.fwd_from.from_id
                    if isinstance(fwd, PeerChannel):
                        forward_from_chat_id = fwd.channel_id
                    elif isinstance(fwd, PeerChat):
                        forward_from_chat_id = fwd.chat_id

                results.append(
                    MessageData(
                        tg_message_id=msg.id,
                        text=msg.message,
                        tg_date=msg.date,
                        sender_id=msg.sender_id,
                        sender_name=sender_name,
                        sender_username=sender_username,
                        forward_from_chat_id=forward_from_chat_id,
                    )
                )

        except ChannelPrivateError:
            raise

        except UserDeactivatedBanError:
            logger.critical("[BAN] UserDeactivatedBanError — stopping")
            raise BannedError("Account banned by Telegram")

        except FloodWaitError as e:
            wait = e.seconds + _FLOOD_PAUSE_BUFFER
            logger.warning("[FLOOD] waiting %ds (%d+10)", wait, e.seconds)
            await asyncio.sleep(wait)
            return results

        except ChatAdminRequiredError:
            logger.warning("ChatAdminRequiredError for %s — skipping", source_url)
            return []

        except UsernameNotOccupiedError:
            logger.warning("UsernameNotOccupiedError for %s", source_url)
            raise

        logger.info("Scraped %d messages from %s", len(results), source_url)
        return results

    async def get_user_profile(self, user_id: int) -> UserProfile | None:
        try:
            full = await self._client(GetFullUserRequest(user_id))
            user = full.users[0]
            return UserProfile(
                id=user.id,
                first_name=user.first_name or "",
                last_name=user.last_name,
                username=user.username,
                bio=full.full_user.about,
                phone=user.phone,
            )
        except (UserDeactivatedError, PeerIdInvalidError) as e:
            logger.debug("Could not fetch profile for user_id=%d: %s", user_id, e)
            return None
        except Exception as e:
            logger.warning("Unexpected error fetching profile user_id=%d: %s", user_id, e)
            return None

    async def enrich_messages_with_bio(
        self, messages: list[MessageData]
    ) -> list[MessageData]:
        unique_ids = {m.sender_id for m in messages if m.sender_id is not None}
        profiles: dict[int, UserProfile | None] = {}

        for sender_id in unique_ids:
            profiles[sender_id] = await self.get_user_profile(sender_id)
            await asyncio.sleep(_PROFILE_PAUSE)

        for msg in messages:
            if msg.sender_id and msg.sender_id in profiles:
                profile = profiles[msg.sender_id]
                if profile:
                    msg.sender_bio = profile.bio

        logger.info(
            "Enriched %d messages; fetched %d profiles", len(messages), len(profiles)
        )
        return messages

    async def search_global_messages(
        self, keyword: str, limit: int = 20
    ) -> list[GlobalSearchResult]:
        """Search Telegram globally for messages containing keyword."""
        from telethon.tl.functions.messages import SearchGlobalRequest
        from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty, PeerChannel, PeerChat

        try:
            result = await self._client(
                SearchGlobalRequest(
                    q=keyword,
                    filter=InputMessagesFilterEmpty(),
                    min_date=None,
                    max_date=None,
                    offset_rate=0,
                    offset_peer=InputPeerEmpty(),
                    offset_id=0,
                    limit=limit,
                )
            )
        except FloodWaitError:
            raise
        except Exception as exc:
            logger.warning("search_global failed for %r: %s", keyword, exc)
            return []

        chat_map = {c.id: c for c in result.chats}

        results: list[GlobalSearchResult] = []
        for msg in result.messages:
            if not getattr(msg, "message", None):
                continue

            peer = msg.peer_id
            if isinstance(peer, PeerChannel):
                chat_id = peer.channel_id
            elif isinstance(peer, PeerChat):
                chat_id = peer.chat_id
            else:
                continue

            chat = chat_map.get(chat_id)
            if chat is None:
                continue

            results.append(
                GlobalSearchResult(
                    chat_id=chat_id,
                    chat_username=getattr(chat, "username", None),
                    chat_title=getattr(chat, "title", None) or str(chat_id),
                    chat_members=getattr(chat, "participants_count", None),
                    message_id=msg.id,
                    message_text=msg.message,
                    message_date=msg.date,
                )
            )

        logger.info("search_global %r → %d results", keyword, len(results))
        return results

    async def get_channel_entity(self, source_url: str) -> tuple[int | None, int | None]:
        """Return (tg_channel_id, tg_access_hash) for a channel URL, or (None, None) on failure."""
        try:
            entity = await self._client.get_entity(source_url)
            return getattr(entity, "id", None), getattr(entity, "access_hash", None)
        except Exception as e:
            logger.debug("get_channel_entity failed for %s: %s", source_url, e)
            return None, None

    async def resolve_by_entity(
        self, channel_id: int, access_hash: int
    ) -> tuple[str | None, str | None]:
        """Find a channel's current username by its stable Telegram entity ID.

        Returns (username, title) where username is the new @handle, or (None, None) if not found.
        """
        from telethon.tl.functions.channels import GetChannelsRequest
        from telethon.tl.types import InputChannel

        try:
            result = await self._client(
                GetChannelsRequest([InputChannel(channel_id, access_hash)])
            )
            if result.chats:
                chat = result.chats[0]
                # Deleted/banned channels return a stub with no title
                if not getattr(chat, "title", None):
                    return None, None
                username = getattr(chat, "username", None)
                # Telethon ≥1.25 also has .usernames (list); fall back to first
                if not username:
                    usernames = getattr(chat, "usernames", None) or []
                    username = usernames[0].username if usernames else None
                title = chat.title
                return username, title
        except Exception as e:
            logger.warning(
                "resolve_by_entity failed for channel_id=%d: %s", channel_id, e
            )
        return None, None

    async def validate_source(self, source_url: str) -> SourceValidation:
        try:
            entity = await self._client.get_entity(source_url)
            title = getattr(entity, "title", source_url)
            members_count = getattr(entity, "participants_count", None)
            tg_channel_id = getattr(entity, "id", None)
            tg_access_hash = getattr(entity, "access_hash", None)
            return SourceValidation(
                is_valid=True,
                title=title,
                members_count=members_count,
                error=None,
                tg_channel_id=tg_channel_id,
                tg_access_hash=tg_access_hash,
            )
        except UsernameNotOccupiedError as e:
            return SourceValidation(
                is_valid=False, title=None, members_count=None, error=str(e)
            )
        except Exception as e:
            logger.warning("validate_source error for %s: %s", source_url, e)
            return SourceValidation(
                is_valid=False, title=None, members_count=None, error=str(e)
            )
