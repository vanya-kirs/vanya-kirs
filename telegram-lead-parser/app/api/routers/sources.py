import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_user_id
from app.api.errors import SourceNotFoundError, SourceValidationError
from app.api.schemas.source import (
    SourceCreate,
    SourceImportRequest,
    SourceImportResponse,
    SourceResponse,
    SourceValidateRequest,
    SourceValidateResponse,
)
from app.core.config import get_settings
from app.listener.sync import publish_source_added
from app.parser.client import TelethonClient
from app.repositories.rejected_source import RejectedSourceRepository
from app.repositories.source import SourceRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["Sources"])


def _telethon_configured(settings) -> bool:
    return bool(settings.API_ID and settings.API_HASH and settings.SESSION_STRING)


@router.post(
    "",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new Telegram source",
    description="Validates the Telegram URL via Telethon (if configured), then saves it to the database.",
)
async def create_source(
    body: SourceCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> SourceResponse:
    settings = get_settings()
    existing = await SourceRepository.get_by_url_for_user(db, body.url, user_id)
    if existing:
        if existing.is_active:
            raise ValueError(f"Source '{body.url}' already exists")
        reactivated = await SourceRepository.reactivate(db, existing.id, name=body.name)
        return SourceResponse.model_validate(reactivated)

    if _telethon_configured(settings):
        async with TelethonClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        ) as client:
            validation = await client.validate_source(body.url)
        if not validation.is_valid:
            raise SourceValidationError(body.url, validation.error or "Unknown error")
    else:
        logger.warning("Telethon not configured — skipping source validation for %s", body.url)

    source = await SourceRepository.create(db, url=body.url, name=body.name, user_id=user_id)
    logger.info("Created source id=%d url=%s", source.id, source.url)

    try:
        await publish_source_added(settings.REDIS_URL, source.id, source.url, user_id)
    except Exception as exc:
        logger.warning("Could not publish source_added event: %s", exc)

    return SourceResponse.model_validate(source)


@router.get(
    "",
    response_model=list[SourceResponse],
    summary="List active sources",
)
async def list_sources(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> list[SourceResponse]:
    sources = await SourceRepository.get_all_active(db, user_id=user_id)
    return [SourceResponse.model_validate(s) for s in sources]


@router.get(
    "/inactive",
    response_model=list[SourceResponse],
    summary="List deactivated sources",
)
async def list_inactive_sources(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> list[SourceResponse]:
    sources = await SourceRepository.get_inactive(db, user_id=user_id)
    return [SourceResponse.model_validate(s) for s in sources]


@router.get(
    "/discovered",
    response_model=list[SourceResponse],
    summary="List sources found via global search",
)
async def list_discovered_sources(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> list[SourceResponse]:
    sources = await SourceRepository.get_by_discovery_method(db, user_id=user_id, method="global_search")
    return [SourceResponse.model_validate(s) for s in sources]


@router.get(
    "/export",
    summary="Export all sources as XLSX",
)
async def export_sources(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> StreamingResponse:
    import openpyxl
    from openpyxl.styles import Font

    sources = await SourceRepository.get_all_active(db, user_id=user_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Источники"

    headers = ["id", "url", "name", "тип", "парсинг", "последний_парсинг", "создан"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for src in sources:
        method_label = "вручную" if src.discovery_method == "manual" else "автопоиск"
        ws.append([
            src.id,
            src.url,
            src.name,
            method_label,
            "да" if src.parsing_enabled else "нет",
            src.last_parsed_at.isoformat() if src.last_parsed_at else "",
            src.created_at.isoformat(),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=sources_{timestamp}.xlsx"},
    )


@router.get(
    "/rejected",
    summary="List rejected sources (too small, broadcast)",
)
async def list_rejected_sources(
    reason: str | None = None,
    min_members: int | None = Query(default=None, ge=0),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> list[dict]:
    items = await RejectedSourceRepository.get_all(
        db, reason=reason, min_members=min_members, limit=limit, offset=offset
    )
    return [
        {
            "id": r.id,
            "url": r.url,
            "name": r.name,
            "reason": r.reason,
            "member_count": r.member_count,
            "discovery_method": r.discovery_method,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
        }
        for r in items
    ]


@router.get(
    "/rejected/count",
    summary="Count rejected sources",
)
async def count_rejected_sources(
    reason: str | None = None,
    min_members: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> dict[str, int]:
    count = await RejectedSourceRepository.count(db, reason=reason, min_members=min_members)
    return {"count": count}


@router.get(
    "/rejected/export",
    summary="Export rejected sources as XLSX",
)
async def export_rejected_sources(
    reason: str | None = None,
    min_members: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> StreamingResponse:
    import openpyxl
    from openpyxl.styles import Font

    items = await RejectedSourceRepository.get_all(
        db, reason=reason, min_members=min_members, limit=10000
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Отклонённые"

    headers = ["url", "name", "причина", "участников", "метод", "последний_раз_видели"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    reason_labels = {"too_small": "мало участников", "broadcast": "канал (не группа)"}
    for r in items:
        ws.append([
            r.url,
            r.name,
            reason_labels.get(r.reason, r.reason),
            r.member_count,
            r.discovery_method,
            r.last_seen_at.isoformat() if r.last_seen_at else "",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=rejected_sources_{timestamp}.xlsx"},
    )


@router.post(
    "/global-search/trigger",
    summary="Trigger global keyword search task",
)
async def trigger_global_search() -> dict:
    from app.tasks.global_search import global_search_task
    task = global_search_task.delay()
    logger.info("global_search_task dispatched: task_id=%s", task.id)
    return {"task_id": task.id, "status": "queued"}


@router.get(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Get source details",
)
async def get_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    source = await SourceRepository.get_by_id(db, source_id)
    if source is None:
        raise SourceNotFoundError(source_id)
    return SourceResponse.model_validate(source)


@router.delete(
    "/{source_id}",
    summary="Deactivate a source",
    description="Sets is_active=False. Does not delete from DB.",
)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    source = await SourceRepository.get_by_id(db, source_id)
    if source is None:
        raise SourceNotFoundError(source_id)
    await SourceRepository.deactivate(db, source_id)
    return {"message": "Source deactivated"}


@router.patch(
    "/{source_id}/parsing",
    response_model=SourceResponse,
    summary="Toggle parsing on/off for a source",
)
async def toggle_source_parsing(
    source_id: int,
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    source = await SourceRepository.get_by_id(db, source_id)
    if source is None:
        raise SourceNotFoundError(source_id)
    updated = await SourceRepository.set_parsing_enabled(db, source_id, not source.parsing_enabled)
    return SourceResponse.model_validate(updated)


@router.post(
    "/import",
    response_model=SourceImportResponse,
    summary="Bulk import sources from a URL list (no Telethon validation)",
)
async def import_sources(
    body: SourceImportRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> SourceImportResponse:
    _TG_PREFIXES = ("@", "https://t.me/", "http://t.me/")
    imported = 0
    skipped = 0
    errors: list[dict] = []

    for item in body.items:
        url = item.url.strip()
        if not url.startswith(_TG_PREFIXES):
            errors.append({"url": url, "error": "invalid URL format"})
            continue
        existing = await SourceRepository.get_by_url_for_user(db, url, user_id)
        if existing:
            skipped += 1
            continue
        name = (item.name or "").strip() or url.lstrip("@").split("/")[-1]
        await SourceRepository.create(db, url=url, name=name, user_id=user_id)
        imported += 1

    logger.info(
        "import_sources: user_id=%d imported=%d skipped=%d errors=%d",
        user_id, imported, skipped, len(errors),
    )
    return SourceImportResponse(imported=imported, skipped=skipped, errors=errors)


@router.post(
    "/validate",
    response_model=SourceValidateResponse,
    summary="Validate a Telegram URL without saving",
)
async def validate_source(body: SourceValidateRequest) -> SourceValidateResponse:
    settings = get_settings()

    if not _telethon_configured(settings):
        # No Telethon credentials — accept any t.me/@ URL as valid (stub mode)
        url = body.url.strip()
        is_valid = url.startswith(("@", "https://t.me/", "http://t.me/"))
        logger.warning("Telethon not configured — returning stub validation for %s", url)
        return SourceValidateResponse(
            is_valid=is_valid,
            title=url.lstrip("@").split("/")[-1],
            members_count=0,
            error=None if is_valid else "Invalid URL format",
        )

    async with TelethonClient(
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        session_string=settings.SESSION_STRING,
    ) as client:
        validation = await client.validate_source(body.url)

    return SourceValidateResponse(
        is_valid=validation.is_valid,
        title=validation.title,
        members_count=validation.members_count,
        error=validation.error,
    )
