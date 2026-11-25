import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_user_id
from app.api.schemas.stats import SourceStats, StatsResponse
from app.core.config import get_settings
from app.listener.health import get_listener_status
from app.repositories.lead import LeadRepository
from app.repositories.message import MessageRepository
from app.repositories.source import SourceRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.get(
    "",
    response_model=StatsResponse,
    summary="Get overall system statistics",
)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> StatsResponse:
    settings = get_settings()
    total_sources = await SourceRepository.count_total(db, user_id)
    active_sources = await SourceRepository.count_active(db, user_id)
    total_messages = await MessageRepository.count_total(db, user_id)
    scored_messages = await MessageRepository.count_scored(db, user_id)
    leads_by_status = await LeadRepository.get_stats(db, user_id)
    total_leads = sum(leads_by_status.values())
    leads_by_score = await LeadRepository.count_by_score_range(db, user_id)
    last_parse_at = await SourceRepository.get_last_parsed_at(db, user_id)
    last_score_at = await LeadRepository.get_last_scored_at(db, user_id)
    listener_health = await get_listener_status(settings.REDIS_URL)

    messages_today = await MessageRepository.count_today(db, user_id)
    scored_today = await MessageRepository.count_scored_today(db, user_id)
    leads_today = await LeadRepository.count_today(db, user_id)

    return StatsResponse(
        total_sources=total_sources,
        active_sources=active_sources,
        total_messages=total_messages,
        scored_messages=scored_messages,
        total_leads=total_leads,
        leads_by_status=leads_by_status,
        leads_by_score=leads_by_score,
        last_parse_at=last_parse_at,
        last_score_at=last_score_at,
        listener_status=listener_health["status"],
        listener_sources_count=active_sources,
        listener_last_heartbeat_at=listener_health["last_heartbeat_at"],
        messages_today=messages_today,
        scored_today=scored_today,
        leads_today=leads_today,
    )


@router.get(
    "/sources",
    response_model=list[SourceStats],
    summary="Get per-source statistics",
)
async def get_source_stats(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> list[SourceStats]:
    stats = await SourceRepository.get_stats_per_source(db, user_id)
    return [SourceStats(**s) for s in stats]
