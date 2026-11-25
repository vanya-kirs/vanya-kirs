from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.criteria import CriteriaProfile
from app.models.lead import Lead
from app.models.message import Message
from app.models.source import Source
from app.repositories.user import UserRepository


async def _seed(db: AsyncSession, user_email: str = "test@example.com") -> Lead:
    user = await UserRepository.get_by_email(db, user_email)
    assert user is not None, "auth_client fixture must create the user first"

    source = Source(url="@g", name="G", user_id=user.id, is_active=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)

    msg = Message(
        source_id=source.id,
        tg_message_id=1,
        tg_date=datetime.now(tz=timezone.utc),
        text="Веду бизнес 3 года",
        sender_name="Иван",
        is_scored=True,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    criteria = CriteriaProfile(
        user_id=user.id,
        name="Test",
        description="Test criteria",
        is_active=True,
        min_score=60,
    )
    db.add(criteria)
    await db.commit()
    await db.refresh(criteria)

    lead = Lead(
        message_id=msg.id,
        criteria_profile_id=criteria.id,
        score=80,
        fit=True,
        reason="Есть опыт и тупик",
        signals=["опыт", "неудовлетворённость"],
        raw_response={"fit": True, "score": 80},
        status="new",
        scored_at=datetime.now(tz=timezone.utc),
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


@pytest.mark.asyncio
async def test_get_leads_empty(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/leads")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_leads_returns_list(auth_client: AsyncClient, test_db: AsyncSession):
    await _seed(test_db)
    response = await auth_client.get("/api/v1/leads")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["score"] == 80
    assert data[0]["fit"] is True
    assert "message" in data[0]
    assert "source" in data[0]


@pytest.mark.asyncio
async def test_get_leads_with_filters(auth_client: AsyncClient, test_db: AsyncSession):
    await _seed(test_db)

    response = await auth_client.get("/api/v1/leads?min_score=90")
    assert response.status_code == 200
    assert response.json() == []

    response = await auth_client.get("/api/v1/leads?min_score=60")
    assert response.status_code == 200
    assert len(response.json()) == 1

    response = await auth_client.get("/api/v1/leads?status=viewed")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_lead_not_found(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/leads/9999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_lead_status(auth_client: AsyncClient, test_db: AsyncSession):
    lead = await _seed(test_db)
    response = await auth_client.patch(
        f"/api/v1/leads/{lead.id}/status",
        json={"status": "viewed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "viewed"


@pytest.mark.asyncio
async def test_update_lead_status_invalid(auth_client: AsyncClient, test_db: AsyncSession):
    lead = await _seed(test_db)
    response = await auth_client.patch(
        f"/api/v1/leads/{lead.id}/status",
        json={"status": "unknown_status"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_leads_require_auth(api_client: AsyncClient):
    response = await api_client.get("/api/v1/leads")
    assert response.status_code == 401
