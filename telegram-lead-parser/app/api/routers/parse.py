import logging

from celery.result import AsyncResult
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_user_id
from app.api.errors import SourceNotFoundError
from app.api.schemas.parse import ParseRunRequest, ParseRunResponse, TaskStatusResponse
from app.repositories.source import SourceRepository
from app.tasks.parse import parse_all_sources_task, parse_source_task
from app.tasks.score import score_source_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/parse", tags=["Parsing"])


@router.post(
    "/run",
    response_model=ParseRunResponse,
    summary="Trigger parsing for one source",
    description="Enqueues parse_source_task for the given source_id. Returns task_id.",
)
async def run_parse(
    body: ParseRunRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> ParseRunResponse:
    source = await SourceRepository.get_by_id(db, body.source_id)
    if source is None or not source.is_active:
        raise SourceNotFoundError(body.source_id)

    task = parse_source_task.delay(body.source_id)
    logger.info("Enqueued parse_source_task id=%s for source_id=%d", task.id, body.source_id)

    return ParseRunResponse(
        task_id=task.id,
        source_id=body.source_id,
        status="queued",
        message=f"Parsing enqueued for source '{source.name}'",
    )


@router.post(
    "/run-all",
    response_model=list[ParseRunResponse],
    summary="Trigger parsing for all active sources",
)
async def run_parse_all(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> list[ParseRunResponse]:
    sources = await SourceRepository.get_all_active(db, user_id=user_id)
    responses = []
    for source in sources:
        task = parse_source_task.delay(source.id)
        responses.append(
            ParseRunResponse(
                task_id=task.id,
                source_id=source.id,
                status="queued",
                message=f"Parsing enqueued for source '{source.name}'",
            )
        )
    return responses


@router.post(
    "/score/{source_id}",
    response_model=ParseRunResponse,
    summary="Trigger scoring for one source",
    description="Enqueues score_source_task for unscored messages in the source.",
)
async def run_score(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_user_id),
) -> ParseRunResponse:
    source = await SourceRepository.get_by_id(db, source_id)
    if source is None or not source.is_active:
        raise SourceNotFoundError(source_id)

    task = score_source_task.delay(source_id, user_id)
    logger.info("Enqueued score_source_task id=%s for source_id=%d", task.id, source_id)

    return ParseRunResponse(
        task_id=task.id,
        source_id=source_id,
        status="queued",
        message=f"Scoring enqueued for source '{source.name}'",
    )


@router.get(
    "/task/{task_id}",
    response_model=TaskStatusResponse,
    summary="Get Celery task status",
)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    result = AsyncResult(task_id)
    state = result.state.lower()  # PENDING → pending, SUCCESS → success, etc.

    task_result = None
    error = None

    if state == "success":
        raw = result.result
        task_result = raw if isinstance(raw, dict) else {"value": str(raw)}
    elif state == "failure":
        error = str(result.result)

    return TaskStatusResponse(
        task_id=task_id,
        status=state,
        result=task_result,
        error=error,
    )
