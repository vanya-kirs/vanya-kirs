import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession


def test_engine_created_with_correct_url(monkeypatch):
    """create_async_engine is called with DATABASE_URL from settings."""
    monkeypatch.setenv("API_ID", "1")
    monkeypatch.setenv("API_HASH", "h")
    monkeypatch.setenv("BOT_TOKEN", "1:A")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("SESSION_STRING", "s")

    import app.core.config as cfg
    cfg.get_settings.cache_clear()
    import importlib
    import app.core.database as db_module
    importlib.reload(db_module)

    assert "localhost" in str(db_module.engine.url)


@pytest.mark.asyncio
async def test_get_db_yields_async_session(monkeypatch):
    """get_db dependency yields an AsyncSession and closes it after use."""
    monkeypatch.setenv("API_ID", "1")
    monkeypatch.setenv("API_HASH", "h")
    monkeypatch.setenv("BOT_TOKEN", "1:A")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("SESSION_STRING", "s")

    import app.core.config as cfg
    cfg.get_settings.cache_clear()
    import importlib
    import app.core.database as db_module
    importlib.reload(db_module)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    # Mock the AsyncSessionLocal to return our mock session context manager
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__ = AsyncMock(return_value=mock_session)
    mock_context_manager.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr(db_module, "AsyncSessionLocal", lambda: mock_context_manager)

    gen = db_module.get_db()
    session = await gen.__anext__()
    assert session is mock_session
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass
