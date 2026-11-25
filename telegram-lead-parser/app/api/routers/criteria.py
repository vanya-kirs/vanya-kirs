import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_user_id
from app.api.errors import CriteriaNotFoundError
from app.api.schemas.criteria import CriteriaCreate, CriteriaResponse, CriteriaUpdate, MinScoreUpdate
from app.repositories.criteria import CriteriaRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/criteria", tags=["Criteria"])


@router.post(
    "",
    response_model=CriteriaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a criteria profile",
)
async def create_criteria(
    body: CriteriaCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> CriteriaResponse:
    profile = await CriteriaRepository.create(
        db,
        user_id=user_id,
        name=body.name,
        description=body.description,
        min_score=body.min_score,
    )
    return CriteriaResponse.model_validate(profile)


@router.get(
    "",
    response_model=list[CriteriaResponse],
    summary="List all criteria profiles",
)
async def list_criteria(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> list[CriteriaResponse]:
    profiles = await CriteriaRepository.get_all(db, user_id)
    return [CriteriaResponse.model_validate(p) for p in profiles]


@router.get(
    "/active",
    response_model=CriteriaResponse,
    summary="Get active criteria profile",
)
async def get_active_criteria(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> CriteriaResponse:
    profile = await CriteriaRepository.get_active(db, user_id)
    if profile is None:
        raise CriteriaNotFoundError()
    return CriteriaResponse.model_validate(profile)


@router.put(
    "/{criteria_id}",
    response_model=CriteriaResponse,
    summary="Update a criteria profile (partial)",
)
async def update_criteria(
    criteria_id: int,
    body: CriteriaUpdate,
    db: AsyncSession = Depends(get_db),
) -> CriteriaResponse:
    existing = await CriteriaRepository.get_by_id(db, criteria_id)
    if existing is None:
        raise CriteriaNotFoundError(criteria_id)

    values = body.model_dump(exclude_none=True)
    if not values:
        return CriteriaResponse.model_validate(existing)

    updated = await CriteriaRepository.update(db, criteria_id, values)
    return CriteriaResponse.model_validate(updated)


@router.patch(
    "/active/min-score",
    response_model=CriteriaResponse,
    summary="Update min_score on the active criteria profile",
)
async def set_active_min_score(
    body: MinScoreUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> CriteriaResponse:
    min_score: int = body.min_score
    profile = await CriteriaRepository.get_active(db, user_id)

    if profile is None:
        # User pre-dates auto-creation — pick any existing profile or create one
        all_profiles = await CriteriaRepository.get_all(db, user_id)
        if all_profiles:
            profile = all_profiles[0]
            await CriteriaRepository.set_active(db, profile.id, user_id)
        else:
            from app.repositories.user import (
                _DEFAULT_CRITERIA_DESCRIPTION,
                _DEFAULT_CRITERIA_NAME,
            )
            profile = await CriteriaRepository.create(
                db,
                user_id=user_id,
                name=_DEFAULT_CRITERIA_NAME,
                description=_DEFAULT_CRITERIA_DESCRIPTION,
                min_score=min_score,
            )
            await CriteriaRepository.set_active(db, profile.id, user_id)
            updated = await CriteriaRepository.get_by_id(db, profile.id)
            return CriteriaResponse.model_validate(updated)

    updated = await CriteriaRepository.update(db, profile.id, {"min_score": min_score})
    return CriteriaResponse.model_validate(updated)


@router.post(
    "/{criteria_id}/activate",
    response_model=CriteriaResponse,
    summary="Set a criteria profile as active",
    description="Deactivates all other profiles for this user, activates the given one.",
)
async def activate_criteria(
    criteria_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> CriteriaResponse:
    existing = await CriteriaRepository.get_by_id(db, criteria_id)
    if existing is None:
        raise CriteriaNotFoundError(criteria_id)

    await CriteriaRepository.set_active(db, criteria_id=criteria_id, user_id=user_id)
    updated = await CriteriaRepository.get_by_id(db, criteria_id)
    return CriteriaResponse.model_validate(updated)
