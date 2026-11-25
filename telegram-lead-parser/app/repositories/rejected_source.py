from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rejected_source import RejectedSource


class RejectedSourceRepository:

    @staticmethod
    async def bulk_upsert(db: AsyncSession, items: list[dict]) -> int:
        """INSERT ... ON CONFLICT (url) DO UPDATE. Returns count of rows inserted/updated."""
        if not items:
            return 0
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        count = 0
        for item in items:
            stmt = (
                pg_insert(RejectedSource)
                .values(
                    url=item["url"],
                    name=item.get("name", ""),
                    reason=item["reason"],
                    member_count=item.get("member_count", 0),
                    discovery_method=item.get("discovery_method", ""),
                    last_seen_at=func.now(),
                )
                .on_conflict_do_update(
                    index_elements=["url"],
                    set_={
                        "member_count": item.get("member_count", 0),
                        "reason": item["reason"],
                        "discovery_method": item.get("discovery_method", ""),
                        "last_seen_at": func.now(),
                        "updated_at": func.now(),
                    },
                )
            )
            await db.execute(stmt)
            count += 1
        await db.commit()
        return count

    @staticmethod
    async def get_all(
        db: AsyncSession,
        reason: str | None = None,
        min_members: int | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[RejectedSource]:
        q = select(RejectedSource)
        if reason:
            q = q.where(RejectedSource.reason == reason)
        if min_members is not None:
            q = q.where(RejectedSource.member_count >= min_members)
        q = q.order_by(RejectedSource.member_count.desc()).limit(limit).offset(offset)
        result = await db.execute(q)
        return list(result.scalars().all())

    @staticmethod
    async def count(
        db: AsyncSession,
        reason: str | None = None,
        min_members: int | None = None,
    ) -> int:
        q = select(func.count()).select_from(RejectedSource)
        if reason:
            q = q.where(RejectedSource.reason == reason)
        if min_members is not None:
            q = q.where(RejectedSource.member_count >= min_members)
        result = await db.execute(q)
        return result.scalar_one()
