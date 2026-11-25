import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# --- Custom exceptions ---

class SourceNotFoundError(Exception):
    def __init__(self, source_id: int) -> None:
        self.source_id = source_id
        super().__init__(f"Source {source_id} not found")


class LeadNotFoundError(Exception):
    def __init__(self, lead_id: int) -> None:
        self.lead_id = lead_id
        super().__init__(f"Lead {lead_id} not found")


class CriteriaNotFoundError(Exception):
    def __init__(self, criteria_id: int | None = None) -> None:
        msg = f"CriteriaProfile {criteria_id} not found" if criteria_id else "No active CriteriaProfile found"
        super().__init__(msg)


class SourceValidationError(Exception):
    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Source URL '{url}' is invalid: {reason}")


class InvalidStatusError(Exception):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"Invalid lead status: '{status}'")


# --- Exception handlers ---

async def source_not_found_handler(request: Request, exc: SourceNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def lead_not_found_handler(request: Request, exc: LeadNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def criteria_not_found_handler(request: Request, exc: CriteriaNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def source_validation_error_handler(
    request: Request, exc: SourceValidationError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


async def invalid_status_handler(request: Request, exc: InvalidStatusError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception on %s %s:\n%s",
        request.method,
        request.url.path,
        traceback.format_exc(),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def register_exception_handlers(app) -> None:  # type: ignore[type-arg]
    app.add_exception_handler(SourceNotFoundError, source_not_found_handler)
    app.add_exception_handler(LeadNotFoundError, lead_not_found_handler)
    app.add_exception_handler(CriteriaNotFoundError, criteria_not_found_handler)
    app.add_exception_handler(SourceValidationError, source_validation_error_handler)
    app.add_exception_handler(InvalidStatusError, invalid_status_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(Exception, generic_error_handler)
