import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.lead import Lead
from app.models.message import Message
from app.models.source import Source
from app.scoring.schemas import ScoringResult

logger = logging.getLogger(__name__)

_LEAD_EXPIRY_DAYS = 2


def _expiry_filter():
    """Condition that hides leads older than 2 days unless they were accepted."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_LEAD_EXPIRY_DAYS)
    return or_(Lead.status == "contacted", Lead.scored_at > cutoff)


class LeadRepository:
    @staticmethod
    async def count_with_filters(
        db: AsyncSession,
        user_id: int,
        status: str | None = None,
        min_score: int | None = None,
        source_id: int | None = None,
    ) -> int:
        query = (
            select(func.count(Lead.id))
            .join(Lead.message)
            .join(Message.source)
            .where(Source.user_id == user_id)
            .where(_expiry_filter())
        )
        if status is not None:
            query = query.where(Lead.status == status)
        if min_score is not None:
            query = query.where(Lead.score >= min_score)
        if source_id is not None:
            query = query.where(Message.source_id == source_id)
        result = await db.execute(query)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def create(
        db: AsyncSession,
        scoring_result: ScoringResult,
        criteria_profile_id: int,
    ) -> Lead:
        lead = Lead(
            message_id=scoring_result.message_id,
            criteria_profile_id=criteria_profile_id,
            score=scoring_result.score,
            fit=scoring_result.fit,
            reason=scoring_result.reason,
            signals=scoring_result.signals,
            raw_response=scoring_result.raw_response,
            status="new",
            scored_at=scoring_result.scored_at,
        )
        db.add(lead)
        await db.commit()
        await db.refresh(lead)
        logger.info(
            "Created Lead id=%d for message_id=%d score=%d",
            lead.id,
            lead.message_id,
            lead.score,
        )
        return lead

    @staticmethod
    async def get_by_message_id(db: AsyncSession, message_id: int) -> Lead | None:
        result = await db.execute(
            select(Lead).where(Lead.message_id == message_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_message_id_with_details(db: AsyncSession, message_id: int) -> Lead | None:
        result = await db.execute(
            select(Lead)
            .options(selectinload(Lead.message).selectinload(Message.source))
            .where(Lead.message_id == message_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        db: AsyncSession,
        user_id: int,
        status: str | None = None,
        min_score: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Lead]:
        query = (
            select(Lead)
            .join(Lead.message)
            .join(Message.source)
            .where(Source.user_id == user_id)
            .where(_expiry_filter())
        )
        if status is not None:
            query = query.where(Lead.status == status)
        if min_score is not None:
            query = query.where(Lead.score >= min_score)
        query = query.order_by(Lead.score.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def update_status(db: AsyncSession, lead_id: int, status: str) -> None:
        await db.execute(
            update(Lead).where(Lead.id == lead_id).values(status=status)
        )
        await db.commit()
        logger.info("Updated Lead id=%d status=%s", lead_id, status)

    @staticmethod
    async def exists(db: AsyncSession, message_id: int) -> bool:
        result = await db.execute(
            select(Lead.id).where(Lead.message_id == message_id)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def get_stats(db: AsyncSession, user_id: int) -> dict[str, int]:
        """Returns count per status for all leads belonging to user."""
        rows = await db.execute(
            select(Lead.status, func.count(Lead.id).label("cnt"))
            .join(Lead.message)
            .join(Message.source)
            .where(Source.user_id == user_id)
            .group_by(Lead.status)
        )
        return {row.status: row.cnt for row in rows}

    @staticmethod
    async def update(
        db: AsyncSession,
        lead_id: int,
        score: int,
        reason: str,
        signals: list[str],
        raw_response: dict,
        fit: bool,
    ) -> None:
        await db.execute(
            update(Lead)
            .where(Lead.id == lead_id)
            .values(score=score, reason=reason, signals=signals, raw_response=raw_response, fit=fit)
        )
        await db.commit()

    @staticmethod
    async def get_by_id(db: AsyncSession, lead_id: int) -> Lead | None:
        result = await db.execute(
            select(Lead)
            .options(
                selectinload(Lead.message).selectinload(Message.source),
            )
            .where(Lead.id == lead_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_with_details(
        db: AsyncSession,
        user_id: int,
        status: str | None = None,
        min_score: int | None = None,
        source_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Lead]:
        query = (
            select(Lead)
            .options(
                selectinload(Lead.message).selectinload(Message.source),
            )
            .join(Lead.message)
            .join(Message.source)
            .where(Source.user_id == user_id)
            .where(_expiry_filter())
        )
        if status is not None:
            query = query.where(Lead.status == status)
        if min_score is not None:
            query = query.where(Lead.score >= min_score)
        if source_id is not None:
            query = query.where(Message.source_id == source_id)
        if status == "contacted":
            query = query.order_by(Lead.scored_at.desc(), Lead.id.desc())
        else:
            query = query.order_by(Lead.score.desc())
        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_for_export(
        db: AsyncSession,
        user_id: int,
        min_score: int = 60,
        status: str | None = None,
    ) -> list[Lead]:
        query = (
            select(Lead)
            .options(
                selectinload(Lead.message).selectinload(Message.source),
            )
            .join(Lead.message)
            .join(Message.source)
            .where(Source.user_id == user_id)
            .where(Lead.score >= min_score)
        )
        if status is not None:
            query = query.where(Lead.status == status)
        query = query.order_by(Lead.score.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_last_scored_at(db: AsyncSession, user_id: int):
        result = await db.execute(
            select(func.max(Lead.scored_at))
            .join(Lead.message)
            .join(Message.source)
            .where(Source.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def delete_old_inactive(db: AsyncSession, days: int = _LEAD_EXPIRY_DAYS) -> int:
        """Delete new/viewed/rejected leads older than `days` days. Returns count deleted."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await db.execute(
            delete(Lead)
            .where(Lead.status.in_(["new", "viewed", "rejected"]))
            .where(Lead.scored_at < cutoff)
        )
        await db.commit()
        deleted = result.rowcount
        if deleted:
            logger.info("Deleted %d expired inactive leads (older than %d days)", deleted, days)
        return deleted

    @staticmethod
    async def count_today(db: AsyncSession, user_id: int) -> int:
        from datetime import date, datetime, timezone
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        result = await db.execute(
            select(func.count(Lead.id))
            .join(Lead.message)
            .join(Message.source)
            .where(Source.user_id == user_id, Lead.scored_at >= today_start)
        )
        return result.scalar_one() or 0

    @staticmethod
    async def count_today_by_source(db: AsyncSession, source_id: int) -> int:
        from datetime import date, datetime, timezone
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        result = await db.execute(
            select(func.count(Lead.id))
            .join(Lead.message)
            .where(Message.source_id == source_id, Lead.scored_at >= today_start)
        )
        return result.scalar_one() or 0

    @staticmethod
    async def count_by_score_range(db: AsyncSession, user_id: int) -> dict[str, int]:
        ranges = {"60-70": (60, 70), "70-80": (70, 80), "80-90": (80, 90), "90-100": (90, 101)}
        result: dict[str, int] = {}
        for label, (lo, hi) in ranges.items():
            row = await db.execute(
                select(func.count(Lead.id))
                .join(Lead.message)
                .join(Message.source)
                .where(Source.user_id == user_id)
                .where(Lead.score >= lo, Lead.score < hi)
            )
            result[label] = row.scalar_one() or 0
        return result
