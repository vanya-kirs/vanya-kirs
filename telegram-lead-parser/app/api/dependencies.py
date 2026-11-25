from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import verify_access_token
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.repositories.criteria import CriteriaRepository
from app.repositories.lead import LeadRepository
from app.repositories.message import MessageRepository
from app.repositories.source import SourceRepository
from app.repositories.user import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        user_id = verify_access_token(token)
    except JWTError:
        raise _credentials_exception

    user = await UserRepository.get_by_id(db, user_id)
    if user is None or not user.is_active:
        raise _credentials_exception
    return user


async def get_user_id(
    current_user: User = Depends(get_current_user),
) -> int:
    return current_user.id


def get_source_repo(db: AsyncSession = Depends(get_db)) -> SourceRepository:
    return SourceRepository()


def get_criteria_repo(db: AsyncSession = Depends(get_db)) -> CriteriaRepository:
    return CriteriaRepository()


def get_lead_repo(db: AsyncSession = Depends(get_db)) -> LeadRepository:
    return LeadRepository()


def get_message_repo(db: AsyncSession = Depends(get_db)) -> MessageRepository:
    return MessageRepository()
