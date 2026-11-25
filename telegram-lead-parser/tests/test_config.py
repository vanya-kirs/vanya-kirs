import pytest
from pydantic import ValidationError


def test_settings_loads_from_env(monkeypatch):
    """Settings loads correctly when all required vars are present."""
    monkeypatch.setenv("API_ID", "12345")
    monkeypatch.setenv("API_HASH", "abc123hash")
    monkeypatch.setenv("BOT_TOKEN", "111:AAA")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("SESSION_STRING", "some_session_string")

    import importlib
    import app.core.config as cfg_module
    importlib.reload(cfg_module)

    settings = cfg_module.Settings()
    assert settings.API_ID == 12345
    assert settings.API_HASH == "abc123hash"
    assert settings.BOT_TOKEN == "111:AAA"
    assert "asyncpg" in settings.DATABASE_URL
    assert settings.REDIS_URL == "redis://localhost:6379/0"
    assert settings.ANTHROPIC_API_KEY == "sk-ant-test"
    assert settings.SESSION_STRING == "some_session_string"


def test_settings_fails_on_missing_required(monkeypatch):
    """Settings raises ValidationError when required vars are absent."""
    for var in ["API_ID", "API_HASH", "BOT_TOKEN", "DATABASE_URL",
                "REDIS_URL", "ANTHROPIC_API_KEY", "SESSION_STRING"]:
        monkeypatch.delenv(var, raising=False)

    import importlib
    import app.core.config as cfg_module
    importlib.reload(cfg_module)

    with pytest.raises(ValidationError):
        cfg_module.Settings(_env_file=None)


def test_api_id_must_be_integer(monkeypatch):
    """API_ID must coerce to int; non-numeric string raises ValidationError."""
    monkeypatch.setenv("API_ID", "not_a_number")
    monkeypatch.setenv("API_HASH", "abc123hash")
    monkeypatch.setenv("BOT_TOKEN", "111:AAA")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("SESSION_STRING", "some_session_string")

    import importlib
    import app.core.config as cfg_module
    importlib.reload(cfg_module)

    with pytest.raises(ValidationError):
        cfg_module.Settings()
