from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.parser.schemas import SourceValidation
from app.repositories.source import SourceRepository
from app.repositories.user import UserRepository


async def _get_auth_user_id(test_db: AsyncSession) -> int:
    """Return id of the user created by auth_client fixture."""
    user = await UserRepository.get_by_email(test_db, "test@example.com")
    return user.id


@pytest.mark.asyncio
async def test_create_source_valid(auth_client: AsyncClient, test_db: AsyncSession):
    user_id = await _get_auth_user_id(test_db)
    mock_validation = SourceValidation(
        is_valid=True, title="Test Group", members_count=100, error=None
    )
    with (
        patch("app.api.routers.sources.TelethonClient") as mock_cls,
        patch("app.api.routers.sources.SourceRepository.create") as mock_create,
        patch("app.api.routers.sources.SourceRepository.get_by_url_for_user", new=AsyncMock(return_value=None)),
        patch("app.api.routers.sources.publish_source_added", new=AsyncMock()),
    ):
        mock_instance = AsyncMock()
        mock_instance.validate_source = AsyncMock(return_value=mock_validation)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        now = datetime.now(timezone.utc)
        source = Source(url="@testgroup", name="Test Group", user_id=user_id, is_active=True)
        source.id = 999
        source.parse_interval_minutes = 15
        source.last_parsed_at = None
        source.requires_join = False
        source.join_queued_at = None
        source.parsing_enabled = True
        source.created_at = now
        source.updated_at = now
        source.discovery_method = "manual"
        source.status = "active"
        mock_create.return_value = source

        response = await auth_client.post(
            "/api/v1/sources",
            json={"url": "@testgroup", "name": "Test Group"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["url"] == "@testgroup"
    assert data["name"] == "Test Group"


@pytest.mark.asyncio
async def test_create_source_invalid_url(auth_client: AsyncClient):
    response = await auth_client.post(
        "/api/v1/sources",
        json={"url": "not-a-telegram-url", "name": "Bad Source"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_source_telegram_invalid(auth_client: AsyncClient):
    mock_validation = SourceValidation(
        is_valid=False, title=None, members_count=None, error="Channel not found"
    )
    with patch("app.api.routers.sources.TelethonClient") as mock_cls:
        mock_instance = AsyncMock()
        mock_instance.validate_source = AsyncMock(return_value=mock_validation)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        response = await auth_client.post(
            "/api/v1/sources",
            json={"url": "@nonexistent", "name": "Bad"},
        )

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_sources_empty(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/sources")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_sources_returns_list(auth_client: AsyncClient, test_db: AsyncSession):
    user_id = await _get_auth_user_id(test_db)
    await SourceRepository.create(test_db, url="@testgroup", name="Test Group", user_id=user_id)

    response = await auth_client.get("/api/v1/sources")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["url"] == "@testgroup"


@pytest.mark.asyncio
async def test_get_source_not_found(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/sources/9999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_source(auth_client: AsyncClient, test_db: AsyncSession):
    user_id = await _get_auth_user_id(test_db)
    source = await SourceRepository.create(
        test_db, url="@delgroup", name="Del Group", user_id=user_id
    )
    response = await auth_client.delete(f"/api/v1/sources/{source.id}")
    assert response.status_code == 200
    assert response.json()["message"] == "Source deactivated"

    list_response = await auth_client.get("/api/v1/sources")
    assert list_response.status_code == 200
    assert list_response.json() == []


@pytest.mark.asyncio
async def test_sources_require_auth(api_client: AsyncClient):
    response = await api_client.get("/api/v1/sources")
    assert response.status_code == 401
