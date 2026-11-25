import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_stats_empty(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_sources"] == 0
    assert data["active_sources"] == 0
    assert data["total_messages"] == 0
    assert data["scored_messages"] == 0
    assert data["total_leads"] == 0
    assert data["leads_by_status"] == {}
    assert data["last_parse_at"] is None
    assert data["last_score_at"] is None


@pytest.mark.asyncio
async def test_get_stats_sources_empty(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/stats/sources")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_health(api_client: AsyncClient):
    response = await api_client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


@pytest.mark.asyncio
async def test_stats_require_auth(api_client: AsyncClient):
    response = await api_client.get("/api/v1/stats")
    assert response.status_code == 401
