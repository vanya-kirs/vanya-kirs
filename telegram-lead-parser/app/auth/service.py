import logging

import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token, create_refresh_token
from app.auth.schemas import TokenResponse
from app.models.user import User
from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


class AuthService:
    @staticmethod
    async def register(
        db: AsyncSession,
        email: str,
        password: str,
        username: str | None = None,
    ) -> TokenResponse:
        if await UserRepository.exists_by_email(db, email):
            raise ValueError(f"Email '{email}' is already registered")

        password_hash = hash_password(password)
        user = await UserRepository.create(
            db, email=email, password_hash=password_hash, username=username
        )
        logger.info("Registered new user id=%d email=%s", user.id, user.email)
        return _issue_tokens(user.id)

    @staticmethod
    async def login(db: AsyncSession, email: str, password: str) -> TokenResponse:
        user = await UserRepository.get_by_email(db, email)
        if user is None or user.password_hash is None:
            raise ValueError("Invalid email or password")
        if not verify_password(password, user.password_hash):
            raise ValueError("Invalid email or password")
        if not user.is_active:
            raise ValueError("User account is disabled")
        logger.info("User id=%d logged in", user.id)
        return _issue_tokens(user.id)

    @staticmethod
    async def refresh(db: AsyncSession, refresh_token: str) -> TokenResponse:
        from jose import JWTError

        from app.auth.jwt import verify_refresh_token

        try:
            user_id = verify_refresh_token(refresh_token)
        except JWTError:
            raise ValueError("Invalid or expired refresh token")

        user = await UserRepository.get_by_id(db, user_id)
        if user is None or not user.is_active:
            raise ValueError("User not found or disabled")

        return _issue_tokens(user_id)

    @staticmethod
    async def get_current_user(db: AsyncSession, user_id: int) -> User:
        user = await UserRepository.get_by_id(db, user_id)
        if user is None:
            raise ValueError("User not found")
        return user


def _issue_tokens(user_id: int) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )
