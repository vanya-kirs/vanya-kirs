import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_register_success(api_client: AsyncClient):
    response = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(api_client: AsyncClient):
    payload = {"email": "dup@example.com", "password": "password123"}
    await api_client.post("/api/v1/auth/register", json=payload)
    response = await api_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_password_too_short(api_client: AsyncClient):
    response = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "x@x.com", "password": "short"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_email(api_client: AsyncClient):
    response = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "password123"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success(api_client: AsyncClient):
    await api_client.post(
        "/api/v1/auth/register",
        json={"email": "login@example.com", "password": "password123"},
    )
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_wrong_password(api_client: AsyncClient):
    await api_client.post(
        "/api/v1/auth/register",
        json={"email": "wp@example.com", "password": "password123"},
    )
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "wp@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_login_unknown_email(api_client: AsyncClient):
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "password123"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_refresh_token(api_client: AsyncClient):
    reg = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "refresh@example.com", "password": "password123"},
    )
    refresh_token = reg.json()["refresh_token"]

    response = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_refresh_with_access_token_fails(api_client: AsyncClient):
    reg = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "rfail@example.com", "password": "password123"},
    )
    access_token = reg.json()["access_token"]

    response = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_token},  # wrong token type
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_me_authenticated(api_client: AsyncClient):
    reg = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "me@example.com", "password": "password123"},
    )
    token = reg.json()["access_token"]

    response = await api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "me@example.com"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_me_no_token(api_client: AsyncClient):
    response = await api_client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(api_client: AsyncClient):
    response = await api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalidtoken"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_requires_auth(api_client: AsyncClient):
    response = await api_client.get("/api/v1/sources")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_with_auth(api_client: AsyncClient):
    reg = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "protected@example.com", "password": "password123"},
    )
    token = reg.json()["access_token"]

    response = await api_client.get(
        "/api/v1/sources",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == []
