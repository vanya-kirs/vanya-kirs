import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_user_id
from app.api.errors import LeadNotFoundError
from app.api.schemas.lead import LeadResponse, LeadStatusUpdate, MessageBrief, SourceBrief
from app.repositories.lead import LeadRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/leads", tags=["Leads"])

VALID_STATUSES = {"new", "viewed", "contacted", "rejected"}


def _build_lead_response(lead) -> LeadResponse:
    msg = lead.message
    src = msg.source
    return LeadResponse(
        id=lead.id,
        score=lead.score,
        fit=lead.fit,
        reason=lead.reason,
        signals=lead.signals or [],
        status=lead.status,
        scored_at=lead.scored_at,
        message=MessageBrief(
            id=msg.id,
            text=msg.text or None,
            sender_name=msg.sender_name,
            sender_username=msg.sender_username,
            sender_bio=msg.sender_bio,
            tg_date=msg.tg_date,
        ),
        source=SourceBrief(id=src.id, url=src.url, name=src.name),
    )


@router.get(
    "",
    response_model=list[LeadResponse],
    summary="List leads with filters",
    description="Returns leads sorted by score DESC. Supports filtering by score, status, source.",
)
async def list_leads(
    min_score: int | None = Query(default=None, ge=0, le=100),
    status: str | None = Query(default=None),
    source_id: int | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> list[LeadResponse]:
    leads = await LeadRepository.get_all_with_details(
        db,
        user_id=user_id,
        status=status,
        min_score=min_score,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return [_build_lead_response(lead) for lead in leads]


@router.get(
    "/count",
    summary="Count leads with filters",
)
async def count_leads(
    min_score: int | None = Query(default=None, ge=0, le=100),
    status: str | None = Query(default=None),
    source_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> dict[str, int]:
    count = await LeadRepository.count_with_filters(
        db,
        user_id=user_id,
        status=status,
        min_score=min_score,
        source_id=source_id,
    )
    return {"count": count}


@router.get(
    "/export",
    summary="Export leads to XLSX",
    description="Downloads an XLSX file with leads filtered by min_score and status.",
)
async def export_leads(
    min_score: int = Query(default=60, ge=0, le=100),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> StreamingResponse:
    import openpyxl
    from openpyxl.styles import Font

    leads = await LeadRepository.get_for_export(
        db, user_id=user_id, min_score=min_score, status=status
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Лиды"

    headers = ["id", "score", "reason", "signals", "sender_name", "sender_username",
               "sender_bio", "text", "source_url", "scored_at"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for lead in leads:
        msg = lead.message
        src = msg.source
        ws.append([
            lead.id,
            lead.score,
            lead.reason,
            "; ".join(lead.signals or []),
            msg.sender_name or "",
            msg.sender_username or "",
            msg.sender_bio or "",
            msg.text or "",
            src.url,
            lead.scored_at.isoformat(),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"leads_{timestamp}.xlsx"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/{lead_id}",
    response_model=LeadResponse,
    summary="Get lead details",
)
async def get_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    lead = await LeadRepository.get_by_id(db, lead_id)
    if lead is None:
        raise LeadNotFoundError(lead_id)
    return _build_lead_response(lead)


@router.patch(
    "/{lead_id}/status",
    response_model=LeadResponse,
    summary="Update lead status",
)
async def update_lead_status(
    lead_id: int,
    body: LeadStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    lead = await LeadRepository.get_by_id(db, lead_id)
    if lead is None:
        raise LeadNotFoundError(lead_id)

    await LeadRepository.update_status(db, lead_id, body.status)
    updated = await LeadRepository.get_by_id(db, lead_id)
    return _build_lead_response(updated)
