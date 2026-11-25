import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.listener.schemas import RawMessage
from app.repositories.message import MessageRepository
from app.repositories.source import SourceRepository

logger = logging.getLogger(__name__)


class MessageProcessor:
    """
    Processes a RawMessage received from ListenerClient:
    1. Resolve source_id from URL
    2. Check for duplicate (already saved)
    3. Save message to DB
    4. Dispatch Celery scoring task
    """

    def __init__(self, source_map: dict[str, int]) -> None:
        # url -> source_id mapping, kept in sync by ListenerService
        self._source_map = source_map

    async def process(self, db: AsyncSession, raw: RawMessage, user_id: int) -> None:
        source_id = self._source_map.get(raw.source_url)
        if source_id is None:
            logger.debug(
                "Processor: unknown source_url=%s, skipping", raw.source_url
            )
            return

        # Duplicate check
        exists = await MessageRepository.exists(db, raw.tg_message_id, source_id)
        if exists:
            logger.debug(
                "Processor: duplicate tg_message_id=%d source_id=%d, skipping",
                raw.tg_message_id,
                source_id,
            )
            return

        # Save to DB
        from app.parser.schemas import MessageData

        msg_data = MessageData(
            tg_message_id=raw.tg_message_id,
            text=raw.text,
            tg_date=raw.tg_date,
            sender_id=raw.sender_id,
            sender_name=raw.sender_name,
            sender_username=raw.sender_username,
            sender_bio=raw.sender_bio,
            forward_from_chat_id=raw.forward_from_chat_id,
        )

        inserted = await MessageRepository.bulk_create(db, [msg_data], source_id)
        if not inserted:
            logger.warning(
                "Processor: bulk_create returned 0 rows for tg_message_id=%d",
                raw.tg_message_id,
            )
            return

        saved_msg = await MessageRepository.get_by_tg_id(db, raw.tg_message_id, source_id)
        if saved_msg is None:
            logger.warning(
                "Processor: could not fetch saved message tg_id=%d source_id=%d",
                raw.tg_message_id,
                source_id,
            )
            return

        message_id = saved_msg.id
        logger.info(
            "Processor: saved message id=%d tg_id=%d source_id=%d",
            message_id,
            raw.tg_message_id,
            source_id,
        )

        # Dispatch scoring task
        from app.tasks.score import score_new_message_task
        score_new_message_task.delay(message_id, user_id)
        logger.info(
            "Processor: queued scoring for message_id=%d user_id=%d",
            message_id,
            user_id,
        )
