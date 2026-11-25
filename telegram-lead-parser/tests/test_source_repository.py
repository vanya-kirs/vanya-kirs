import pytest

from app.repositories.source import SourceRepository
from app.models.user import User


@pytest.fixture
async def user_in_db(db_session):
    """Create a user needed for FK constraint on sources."""
    user = User(telegram_id=100001, username="testowner")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_create_source(db_session, user_in_db):
    source = await SourceRepository.create(
        db_session,
        url="https://t.me/testchannel",
        name="Test Channel",
        user_id=user_in_db.id,
    )
    assert source.id is not None
    assert source.url == "https://t.me/testchannel"
    assert source.is_active is True


async def test_get_by_id_found(db_session, user_in_db):
    created = await SourceRepository.create(
        db_session, url="https://t.me/ch1", name="Ch1", user_id=user_in_db.id
    )
    found = await SourceRepository.get_by_id(db_session, created.id)
    assert found is not None
    assert found.id == created.id


async def test_get_by_id_not_found(db_session):
    found = await SourceRepository.get_by_id(db_session, 99999)
    assert found is None


async def test_get_all_active(db_session, user_in_db):
    await SourceRepository.create(
        db_session, url="https://t.me/active1", name="Active1", user_id=user_in_db.id
    )
    await SourceRepository.create(
        db_session, url="https://t.me/active2", name="Active2", user_id=user_in_db.id
    )
    sources = await SourceRepository.get_all_active(db_session, user_id=user_in_db.id)
    assert len(sources) == 2


async def test_deactivate(db_session, user_in_db):
    source = await SourceRepository.create(
        db_session, url="https://t.me/todeactivate", name="ToDeactivate", user_id=user_in_db.id
    )
    await SourceRepository.deactivate(db_session, source.id)
    found = await SourceRepository.get_by_id(db_session, source.id)
    assert found.is_active is False


async def test_update_last_parsed(db_session, user_in_db):
    from datetime import datetime, timezone

    source = await SourceRepository.create(
        db_session, url="https://t.me/toparsed", name="ToParsed", user_id=user_in_db.id
    )
    assert source.last_parsed_at is None

    now = datetime.now(timezone.utc)
    await SourceRepository.update_last_parsed(db_session, source.id, now)

    found = await SourceRepository.get_by_id(db_session, source.id)
    assert found.last_parsed_at is not None
