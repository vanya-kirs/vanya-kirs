import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.message import Message
from app.models.source import Source

logger = logging.getLogger(__name__)


class SourceRepository:
    @staticmethod
    async def get_by_id(db: AsyncSession, source_id: int) -> Source | None:
        result = await db.execute(select(Source).where(Source.id == source_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_active(
        db: AsyncSession,
        user_id: int | None = None,
        parsing_only: bool = False,
    ) -> list[Source]:
        """Return non-deleted sources. If parsing_only=True, also filter by parsing_enabled."""
        query = select(Source).where(Source.is_active == True)  # noqa: E712
        if user_id is not None:
            query = query.where(Source.user_id == user_id)
        if parsing_only:
            query = query.where(Source.parsing_enabled == True)  # noqa: E712
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def set_parsing_enabled(
        db: AsyncSession, source_id: int, enabled: bool
    ) -> Source | None:
        await db.execute(
            update(Source).where(Source.id == source_id).values(parsing_enabled=enabled)
        )
        await db.commit()
        result = await db.execute(select(Source).where(Source.id == source_id))
        src = result.scalar_one_or_none()
        logger.info("Set parsing_enabled=%s for source id=%d", enabled, source_id)
        return src

    @staticmethod
    async def create(
        db: AsyncSession, url: str, name: str, user_id: int
    ) -> Source:
        source = Source(url=url, name=name, user_id=user_id)
        db.add(source)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ValueError(f"Source with url '{url}' already exists")
        await db.refresh(source)
        logger.info("Created source id=%d url=%s", source.id, source.url)
        return source

    @staticmethod
    async def update_last_parsed(
        db: AsyncSession,
        source_id: int,
        parsed_at: datetime,
        last_tg_message_id: int | None = None,
    ) -> None:
        values: dict = {"last_parsed_at": parsed_at}
        if last_tg_message_id is not None:
            values["last_tg_message_id"] = last_tg_message_id
        await db.execute(
            update(Source).where(Source.id == source_id).values(**values)
        )
        await db.commit()
        logger.debug("Updated last_parsed_at for source id=%d", source_id)

    @staticmethod
    async def deactivate(db: AsyncSession, source_id: int) -> None:
        await db.execute(
            update(Source).where(Source.id == source_id).values(is_active=False)
        )
        await db.commit()
        logger.info("Deactivated source id=%d", source_id)

    @staticmethod
    async def set_status(db: AsyncSession, source_id: int, status: str) -> None:
        await db.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(status=status, requires_join=False, parsing_enabled=False)
        )
        await db.commit()
        logger.info("Set source id=%d status=%s", source_id, status)

    @staticmethod
    async def count_active(db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.count(Source.id))
            .where(Source.user_id == user_id, Source.is_active == True)  # noqa: E712
        )
        return result.scalar_one() or 0

    @staticmethod
    async def count_total(db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.count(Source.id)).where(Source.user_id == user_id)
        )
        return result.scalar_one() or 0

    @staticmethod
    async def get_last_parsed_at(db: AsyncSession, user_id: int):
        result = await db.execute(
            select(func.max(Source.last_parsed_at)).where(Source.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_stats_per_source(db: AsyncSession, user_id: int) -> list[dict]:
        from datetime import date, datetime, timezone
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)

        sources = await db.execute(
            select(Source).where(Source.user_id == user_id)
        )
        sources_list = list(sources.scalars().all())

        result = []
        for src in sources_list:
            total_msg = await db.execute(
                select(func.count(Message.id)).where(Message.source_id == src.id)
            )
            scored_msg = await db.execute(
                select(func.count(Message.id))
                .where(Message.source_id == src.id, Message.is_scored == True)  # noqa: E712
            )
            leads_count = await db.execute(
                select(func.count(Lead.id))
                .join(Lead.message)
                .where(Message.source_id == src.id)
            )
            msgs_today = await db.execute(
                select(func.count(Message.id))
                .where(Message.source_id == src.id, Message.tg_date >= today_start)
            )
            scored_today = await db.execute(
                select(func.count(Message.id))
                .where(
                    Message.source_id == src.id,
                    Message.tg_date >= today_start,
                    Message.is_scored == True,  # noqa: E712
                )
            )
            leads_today = await db.execute(
                select(func.count(Lead.id))
                .join(Lead.message)
                .where(Message.source_id == src.id, Lead.scored_at >= today_start)
            )
            result.append(
                {
                    "id": src.id,
                    "name": src.name,
                    "url": src.url,
                    "total_messages": total_msg.scalar_one() or 0,
                    "scored_messages": scored_msg.scalar_one() or 0,
                    "leads_found": leads_count.scalar_one() or 0,
                    "last_parsed_at": src.last_parsed_at,
                    "messages_today": msgs_today.scalar_one() or 0,
                    "scored_today": scored_today.scalar_one() or 0,
                    "leads_today": leads_today.scalar_one() or 0,
                }
            )
        return result

    @staticmethod
    async def get_by_url_for_user(
        db: AsyncSession, url: str, user_id: int
    ) -> "Source | None":
        result = await db.execute(
            select(Source).where(
                Source.url == url,
                Source.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def reactivate(
        db: AsyncSession, source_id: int, name: str | None = None
    ) -> Source | None:
        values = {"is_active": True}
        if name:
            values["name"] = name
        await db.execute(
            update(Source).where(Source.id == source_id).values(**values)
        )
        await db.commit()
        result = await db.execute(select(Source).where(Source.id == source_id))
        src = result.scalar_one_or_none()
        if src:
            logger.info("Reactivated source id=%d", src.id)
        return src

    @staticmethod
    async def update_parse_interval(
        db: AsyncSession, source_id: int, interval_minutes: int
    ) -> None:
        await db.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(parse_interval_minutes=interval_minutes)
        )
        await db.commit()
        logger.debug("Updated parse_interval_minutes=%d for source id=%d", interval_minutes, source_id)

    @staticmethod
    async def get_due_sources(db: AsyncSession) -> list[Source]:
        """Return active parsing-enabled sources due for a parse, most overdue first."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Source).where(
                Source.is_active == True,  # noqa: E712
                Source.parsing_enabled == True,  # noqa: E712
            )
        )
        sources = list(result.scalars().all())

        due: list[tuple[float, Source]] = []
        for s in sources:
            if s.last_parsed_at is None:
                due.append((float("inf"), s))
            else:
                elapsed = (now - s.last_parsed_at).total_seconds() / 60
                overdue = elapsed - s.parse_interval_minutes
                if overdue >= 0:
                    due.append((overdue, s))

        due.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in due]

    @staticmethod
    async def update_join_fields(
        db: AsyncSession,
        source_id: int,
        requires_join: bool,
        join_queued_at: datetime | None,
    ) -> None:
        await db.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(requires_join=requires_join, join_queued_at=join_queued_at)
        )
        await db.commit()

    @staticmethod
    async def get_by_discovery_method(
        db: AsyncSession, user_id: int, method: str
    ) -> list[Source]:
        result = await db.execute(
            select(Source).where(
                Source.user_id == user_id,
                Source.is_active == True,  # noqa: E712
                Source.discovery_method == method,
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_or_create_for_global_search(
        db: AsyncSession, url: str, name: str, user_id: int
    ) -> Source:
        """Find existing source by URL (any user) or create with discovery_method='global_search'."""
        result = await db.execute(select(Source).where(Source.url == url))
        src = result.scalar_one_or_none()
        if src:
            if not src.is_active:
                await db.execute(update(Source).where(Source.id == src.id).values(is_active=True))
                await db.commit()
                await db.refresh(src)
            return src
        src = Source(url=url, name=name, user_id=user_id, discovery_method="global_search")
        db.add(src)
        await db.commit()
        await db.refresh(src)
        logger.info("global_search: created source id=%d url=%s", src.id, url)
        return src

    @staticmethod
    async def update_tg_entity(
        db: AsyncSession,
        source_id: int,
        tg_channel_id: int,
        tg_access_hash: int,
    ) -> None:
        await db.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(tg_channel_id=tg_channel_id, tg_access_hash=tg_access_hash)
        )
        await db.commit()
        logger.debug("Saved tg_entity id=%d hash=*** for source_id=%d", tg_channel_id, source_id)

    @staticmethod
    async def get_inactive(db: AsyncSession, user_id: int) -> list[Source]:
        result = await db.execute(
            select(Source).where(
                Source.user_id == user_id,
                Source.is_active == False,  # noqa: E712
            ).order_by(Source.updated_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_url(
        db: AsyncSession,
        source_id: int,
        new_url: str,
    ) -> None:
        await db.execute(
            update(Source).where(Source.id == source_id).values(url=new_url)
        )
        await db.commit()
        logger.info("Updated url to %s for source_id=%d", new_url, source_id)
