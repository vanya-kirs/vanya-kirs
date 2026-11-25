import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.auth.schemas import (
    BotLoginRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.service import AuthService, _issue_tokens
from app.core.config import get_settings
from app.models.user import User
from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    summary="Register a new user",
    description="Creates a new account with email and password. Returns access and refresh tokens.",
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    return await AuthService.register(
        db, email=body.email, password=body.password, username=body.username
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
    description="Returns access token (60 min) and refresh token (30 days).",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    return await AuthService.login(db, email=body.email, password=body.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access + refresh token pair.",
)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    return await AuthService.refresh(db, refresh_token=body.refresh_token)


@router.post(
    "/bot",
    response_model=TokenResponse,
    summary="Bot internal auth (no email/password required)",
    description="Used by the Telegram bot to authenticate. Validates BOT_TOKEN, auto-creates user.",
)
async def bot_login(
    body: BotLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    if body.bot_token != settings.BOT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid bot token")
    user = await UserRepository.get_or_create_telegram(db, telegram_id=body.telegram_id)
    return _issue_tokens(user.id)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user info",
)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)
