import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.criteria import CriteriaProfile

logger = logging.getLogger(__name__)


class CriteriaRepository:
    @staticmethod
    async def get_active(db: AsyncSession, user_id: int) -> CriteriaProfile | None:
        result = await db.execute(
            select(CriteriaProfile).where(
                CriteriaProfile.user_id == user_id,
                CriteriaProfile.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(db: AsyncSession, criteria_id: int) -> CriteriaProfile | None:
        result = await db.execute(
            select(CriteriaProfile).where(CriteriaProfile.id == criteria_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: int,
        name: str,
        description: str,
        min_score: int = 60,
    ) -> CriteriaProfile:
        profile = CriteriaProfile(
            user_id=user_id,
            name=name,
            description=description,
            min_score=min_score,
            is_active=False,
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        logger.info("Created CriteriaProfile id=%d for user_id=%d", profile.id, user_id)
        return profile

    @staticmethod
    async def set_active(db: AsyncSession, criteria_id: int, user_id: int) -> None:
        """Deactivate all profiles for user, then activate the given one."""
        await db.execute(
            update(CriteriaProfile)
            .where(CriteriaProfile.user_id == user_id)
            .values(is_active=False)
        )
        await db.execute(
            update(CriteriaProfile)
            .where(CriteriaProfile.id == criteria_id, CriteriaProfile.user_id == user_id)
            .values(is_active=True)
        )
        await db.commit()
        logger.info("Set CriteriaProfile id=%d active for user_id=%d", criteria_id, user_id)

    @staticmethod
    async def get_all(db: AsyncSession, user_id: int) -> list[CriteriaProfile]:
        result = await db.execute(
            select(CriteriaProfile).where(CriteriaProfile.user_id == user_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def update(
        db: AsyncSession,
        criteria_id: int,
        values: dict[str, Any],
    ) -> CriteriaProfile | None:
        await db.execute(
            update(CriteriaProfile)
            .where(CriteriaProfile.id == criteria_id)
            .values(**values)
        )
        await db.commit()
        result = await db.execute(
            select(CriteriaProfile).where(CriteriaProfile.id == criteria_id)
        )
        return result.scalar_one_or_none()
