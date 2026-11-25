import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_user
from app.api.schemas.profile import ParseToggleRequest, ProfileResponse
from app.models.user import User
from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profile", tags=["Profile"])

SUBSCRIPTION_DAYS = 30


def _is_subscription_active(user: User) -> bool:
    if user.subscription_until is None:
        return False
    return user.subscription_until > datetime.now(timezone.utc)


def _to_response(user: User) -> ProfileResponse:
    return ProfileResponse(
        id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        subscription_until=user.subscription_until,
        parsing_enabled=user.parsing_enabled,
        subscription_active=_is_subscription_active(user),
    )


@router.get("", response_model=ProfileResponse, summary="Get current user profile")
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    # Refresh to get latest data
    user = await UserRepository.get_by_id(db, current_user.id)
    return _to_response(user)


@router.post("/subscribe", response_model=ProfileResponse, summary="Extend subscription by 30 days")
async def extend_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    user = await UserRepository.extend_subscription(db, current_user.id, days=SUBSCRIPTION_DAYS)
    logger.info("User id=%d extended subscription", current_user.id)
    return _to_response(user)


@router.patch("/parsing", response_model=ProfileResponse, summary="Toggle parsing on/off")
async def toggle_parsing(
    body: ParseToggleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    user = await UserRepository.set_parsing_enabled(db, current_user.id, body.enabled)
    return _to_response(user)
