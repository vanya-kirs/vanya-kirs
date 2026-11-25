import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.errors import register_exception_handlers
from app.api.routers import criteria, leads, parse, profile, sources, stats
from app.auth.router import router as auth_router
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Telegram Lead Parser API starting up on :8000")
    yield
    logger.info("Telegram Lead Parser API shutting down")


app = FastAPI(
    title="Telegram Lead Parser API",
    description=(
        "API for managing Telegram sources, running parsing/scoring jobs, "
        "and viewing AI-qualified leads.\n\n"
        "**Authentication:** Register via `POST /api/v1/auth/register`, "
        "then use the returned `access_token` as a Bearer token in the "
        "Authorize button above."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    swagger_ui_oauth2_redirect_url="/api/v1/auth/login",
)

# Exception handlers
register_exception_handlers(app)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# Auth router (public endpoints)
app.include_router(auth_router, prefix="/api/v1")

# Protected routers
app.include_router(sources.router, prefix="/api/v1")
app.include_router(criteria.router, prefix="/api/v1")
app.include_router(leads.router, prefix="/api/v1")
app.include_router(parse.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(profile.router, prefix="/api/v1")


@app.get("/", tags=["Health"])
@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}
