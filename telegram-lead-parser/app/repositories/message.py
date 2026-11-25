import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.source import Source
from app.parser.schemas import MessageData
from app.scoring.dedup import text_hash as compute_text_hash


def _today_start() -> datetime:
    return datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)

logger = logging.getLogger(__name__)


class MessageRepository:
    @staticmethod
    async def get_by_tg_id(
        db: AsyncSession, tg_message_id: int, source_id: int
    ) -> Message | None:
        result = await db.execute(
            select(Message).where(
                Message.tg_message_id == tg_message_id,
                Message.source_id == source_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession, message_data: MessageData, source_id: int
    ) -> Message:
        msg = Message(
            source_id=source_id,
            tg_message_id=message_data.tg_message_id,
            text=message_data.text,
            tg_date=message_data.tg_date,
            sender_id=message_data.sender_id,
            sender_name=message_data.sender_name,
            sender_username=message_data.sender_username,
            sender_bio=message_data.sender_bio,
            text_hash=compute_text_hash(message_data.text) if message_data.text else None,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg

    @staticmethod
    async def bulk_create(
        db: AsyncSession, messages_data: list[MessageData], source_id: int
    ) -> int:
        """Insert messages with idempotency. Returns count of newly inserted rows."""
        if not messages_data:
            return 0

        # Detect dialect — use PostgreSQL ON CONFLICT DO NOTHING in production,
        # check-then-insert fallback for SQLite (tests)
        try:
            bind = db.get_bind()
            dialect_name = bind.dialect.name
        except Exception:
            dialect_name = "sqlite"

        values = [
            {
                "source_id": source_id,
                "tg_message_id": m.tg_message_id,
                "text": m.text,
                "tg_date": m.tg_date,
                "sender_id": m.sender_id,
                "sender_name": m.sender_name,
                "sender_username": m.sender_username,
                "sender_bio": m.sender_bio,
                "text_hash": compute_text_hash(m.text) if m.text else None,
                "forward_from_chat_id": m.forward_from_chat_id,
            }
            for m in messages_data
        ]

        if dialect_name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(Message).values(values).on_conflict_do_nothing(
                index_elements=["source_id", "tg_message_id"]
            )
            result = await db.execute(stmt)
            await db.commit()
            inserted = result.rowcount
        else:
            # SQLite fallback: check-then-insert (used in tests)
            inserted = 0
            for v in values:
                exists_result = await db.execute(
                    select(Message.id).where(
                        Message.tg_message_id == v["tg_message_id"],
                        Message.source_id == v["source_id"],
                    )
                )
                if exists_result.scalar_one_or_none() is None:
                    db.add(Message(**v))
                    inserted += 1
            await db.commit()

        logger.info(
            "bulk_create: inserted %d / %d messages for source_id=%d",
            inserted,
            len(messages_data),
            source_id,
        )
        return inserted

    @staticmethod
    async def exists(
        db: AsyncSession, tg_message_id: int, source_id: int
    ) -> bool:
        result = await db.execute(
            select(Message.id).where(
                Message.tg_message_id == tg_message_id,
                Message.source_id == source_id,
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def update_sender_profile(
        db: AsyncSession,
        message_id: int,
        bio: str | None,
        phone: str | None,
    ) -> None:
        from sqlalchemy import update as sa_update
        await db.execute(
            sa_update(Message)
            .where(Message.id == message_id)
            .values(sender_bio=bio, sender_phone=phone)
        )
        await db.commit()

    @staticmethod
    async def mark_scored(db: AsyncSession, message_id: int) -> None:
        await db.execute(
            sa_update(Message).where(Message.id == message_id).values(is_scored=True)
        )
        await db.commit()

    @staticmethod
    async def claim_for_scoring(db: AsyncSession, message_ids: list[int]) -> list[int]:
        """Atomically mark messages as scored and return the IDs that were claimed.

        Uses UPDATE ... WHERE is_scored=FALSE so concurrent workers cannot
        double-score the same message. Returns only the IDs actually claimed.
        """
        if not message_ids:
            return []
        result = await db.execute(
            sa_update(Message)
            .where(Message.id.in_(message_ids), Message.is_scored == False)  # noqa: E712
            .values(is_scored=True)
            .returning(Message.id)
        )
        await db.commit()
        return [row[0] for row in result.fetchall()]

    @staticmethod
    async def unclaim_messages(db: AsyncSession, message_ids: list[int]) -> None:
        """Revert claim_for_scoring — restore is_scored=False so messages are retried next run."""
        if not message_ids:
            return
        await db.execute(
            sa_update(Message)
            .where(Message.id.in_(message_ids))
            .values(is_scored=False, skip_reason=None)
        )
        await db.commit()

    @staticmethod
    async def get_unscored(db: AsyncSession, source_id: int, limit: int = 100) -> list[Message]:
        """Return unscored messages for a specific source."""
        result = await db.execute(
            select(Message)
            .where(Message.source_id == source_id, Message.is_scored == False)  # noqa: E712
            .where(Message.text.isnot(None))
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_unscored_all(db: AsyncSession, limit: int = 100) -> list[Message]:
        """Return unscored messages across all sources."""
        result = await db.execute(
            select(Message)
            .where(Message.is_scored == False)  # noqa: E712
            .where(Message.text.isnot(None))
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_total(db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.count(Message.id))
            .join(Message.source)
            .where(Source.user_id == user_id)
        )
        return result.scalar_one() or 0

    @staticmethod
    async def count_scored(db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.count(Message.id))
            .join(Message.source)
            .where(Source.user_id == user_id)
            .where(Message.is_scored == True)  # noqa: E712
        )
        return result.scalar_one() or 0

    @staticmethod
    async def has_scored_text_hash(db: AsyncSession, hash_value: str) -> bool:
        """True if any already-scored message has this text hash (exact repost)."""
        result = await db.execute(
            select(Message.id)
            .where(Message.text_hash == hash_value, Message.is_scored == True)  # noqa: E712
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def get_lead_texts_by_sender(db: AsyncSession, sender_id: int) -> list[str]:
        """Return texts of messages that became leads for this sender_id."""
        from app.models.lead import Lead
        result = await db.execute(
            select(Message.text)
            .join(Lead, Lead.message_id == Message.id)
            .where(Message.sender_id == sender_id, Message.text.isnot(None))
            .limit(20)
        )
        return [row[0] for row in result.fetchall()]

    @staticmethod
    async def count_today(db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.count(Message.id))
            .join(Message.source)
            .where(Source.user_id == user_id, Message.tg_date >= _today_start())
        )
        return result.scalar_one() or 0

    @staticmethod
    async def count_scored_today(db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.count(Message.id))
            .join(Message.source)
            .where(
                Source.user_id == user_id,
                Message.tg_date >= _today_start(),
                Message.is_scored == True,  # noqa: E712
            )
        )
        return result.scalar_one() or 0

    @staticmethod
    async def count_today_by_source(db: AsyncSession, source_id: int) -> int:
        result = await db.execute(
            select(func.count(Message.id))
            .where(Message.source_id == source_id, Message.tg_date >= _today_start())
        )
        return result.scalar_one() or 0

    @staticmethod
    async def count_scored_today_by_source(db: AsyncSession, source_id: int) -> int:
        result = await db.execute(
            select(func.count(Message.id))
            .where(
                Message.source_id == source_id,
                Message.tg_date >= _today_start(),
                Message.is_scored == True,  # noqa: E712
            )
        )
        return result.scalar_one() or 0

    @staticmethod
    async def set_skip_reason_bulk(
        db: AsyncSession, message_ids: list[int], reason: str
    ) -> None:
        if not message_ids:
            return
        await db.execute(
            sa_update(Message)
            .where(Message.id.in_(message_ids))
            .values(score_skip_reason=reason)
        )
        await db.commit()

    @staticmethod
    async def get_all_skipped_for_export(db: AsyncSession) -> list[Message]:
        result = await db.execute(
            select(Message)
            .where(Message.score_skip_reason.isnot(None))
            .order_by(Message.score_skip_reason, Message.tg_date.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def clear_all_skip_reasons(db: AsyncSession) -> int:
        result = await db.execute(
            sa_update(Message)
            .where(Message.score_skip_reason.isnot(None))
            .values(score_skip_reason=None)
        )
        await db.commit()
        return result.rowcount
