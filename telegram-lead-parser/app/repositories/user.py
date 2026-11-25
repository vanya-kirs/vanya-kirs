import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.criteria import CriteriaProfile
from app.models.user import User

logger = logging.getLogger(__name__)

_DEFAULT_CRITERIA_NAME = "Предприниматели"
_DEFAULT_CRITERIA_DESCRIPTION = (
    "Ищем предпринимателей: владельцев бизнеса, основателей стартапов, самозанятых. "
    "Признаки: упоминание своего дела, бизнеса, выручки, команды, продукта или услуги. "
    "Не подходят: наёмные сотрудники, студенты без бизнеса, спамеры."
)
_DEFAULT_CRITERIA_MIN_SCORE = 60


class UserRepository:
    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: int) -> User | None:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        result = await db.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_telegram_id(db: AsyncSession, telegram_id: int) -> User | None:
        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        email: str,
        password_hash: str,
        username: str | None = None,
    ) -> User:
        user = User(
            email=email.lower(),
            password_hash=password_hash,
            username=username,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("Created user id=%d email=%s", user.id, user.email)
        return user

    @staticmethod
    async def extend_subscription(
        db: AsyncSession,
        user_id: int,
        days: int = 30,
    ) -> User | None:
        user = await UserRepository.get_by_id(db, user_id)
        if user is None:
            return None
        now = datetime.now(timezone.utc)
        base = user.subscription_until if (user.subscription_until and user.subscription_until > now) else now
        new_until = base + timedelta(days=days)
        await db.execute(
            update(User).where(User.id == user_id).values(subscription_until=new_until)
        )
        await db.commit()
        await db.refresh(user)
        logger.info("Extended subscription for user_id=%d until %s", user_id, new_until)
        return user

    @staticmethod
    async def set_parsing_enabled(
        db: AsyncSession,
        user_id: int,
        enabled: bool,
    ) -> User | None:
        await db.execute(
            update(User).where(User.id == user_id).values(parsing_enabled=enabled)
        )
        await db.commit()
        user = await UserRepository.get_by_id(db, user_id)
        logger.info("Set parsing_enabled=%s for user_id=%d", enabled, user_id)
        return user

    @staticmethod
    async def exists_by_email(db: AsyncSession, email: str) -> bool:
        result = await db.execute(
            select(User.id).where(User.email == email.lower())
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def get_or_create_telegram(
        db: AsyncSession,
        telegram_id: int,
        username: str | None = None,
    ) -> User:
        user = await UserRepository.get_by_telegram_id(db, telegram_id)
        if user is None:
            user = User(telegram_id=telegram_id, username=username, is_active=True)
            db.add(user)
            await db.flush()  # get user.id before creating criteria
            profile = CriteriaProfile(
                user_id=user.id,
                name=_DEFAULT_CRITERIA_NAME,
                description=_DEFAULT_CRITERIA_DESCRIPTION,
                min_score=_DEFAULT_CRITERIA_MIN_SCORE,
                is_active=True,
            )
            db.add(profile)
            await db.commit()
            await db.refresh(user)
            logger.info(
                "Created user via Telegram id=%d tg_id=%d with default criteria",
                user.id, telegram_id,
            )
        return user
