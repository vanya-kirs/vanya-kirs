import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# NullPool: every AsyncSessionLocal() open/close creates and destroys one real
# connection. This prevents connection exhaustion across multiple processes
# (API, Celery worker, Celery beat) and solves the "Future attached to a
# different loop" problem that arises when Celery tasks spin up new event loops
# via asyncio.run() while inheriting pooled connections from the import-time
# loop. The overhead of a new connection per request is negligible at this
# project's query rate.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    poolclass=NullPool,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def dispose_engine() -> None:
    """No-op with NullPool — kept for backwards-compatibility with Celery tasks
    that call it before asyncio.run()."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
