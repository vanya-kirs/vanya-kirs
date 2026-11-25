from datetime import datetime, timezone

import pytest

from app.models.source import Source
from app.models.user import User
from app.parser.schemas import MessageData
from app.repositories.message import MessageRepository


@pytest.fixture
async def source_in_db(db_session):
    """Create user + source needed for FK constraints."""
    user = User(telegram_id=200001, username="msg_owner")
    db_session.add(user)
    await db_session.flush()

    source = Source(url="https://t.me/msg_src", name="Msg Src", user_id=user.id)
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    return source


def _make_msg(tg_message_id: int = 1) -> MessageData:
    return MessageData(
        tg_message_id=tg_message_id,
        text="Hello lead!",
        tg_date=datetime.now(timezone.utc),
        sender_id=999,
        sender_name="John",
        sender_username="johndoe",
        sender_bio="CEO at Acme",
    )


async def test_create_message(db_session, source_in_db):
    msg = await MessageRepository.create(db_session, _make_msg(1), source_in_db.id)
    assert msg.id is not None
    assert msg.tg_message_id == 1
    assert msg.text == "Hello lead!"
    assert msg.source_id == source_in_db.id


async def test_get_by_tg_id_found(db_session, source_in_db):
    await MessageRepository.create(db_session, _make_msg(42), source_in_db.id)
    found = await MessageRepository.get_by_tg_id(db_session, 42, source_in_db.id)
    assert found is not None
    assert found.tg_message_id == 42


async def test_get_by_tg_id_not_found(db_session, source_in_db):
    found = await MessageRepository.get_by_tg_id(db_session, 99999, source_in_db.id)
    assert found is None


async def test_exists_true(db_session, source_in_db):
    await MessageRepository.create(db_session, _make_msg(10), source_in_db.id)
    result = await MessageRepository.exists(db_session, 10, source_in_db.id)
    assert result is True


async def test_exists_false(db_session, source_in_db):
    result = await MessageRepository.exists(db_session, 10, source_in_db.id)
    assert result is False


async def test_get_unscored(db_session, source_in_db):
    for i in range(3):
        await MessageRepository.create(db_session, _make_msg(i + 100), source_in_db.id)
    msgs = await MessageRepository.get_unscored_all(db_session, limit=10)
    assert len(msgs) == 3


async def test_bulk_create_returns_count(db_session, source_in_db):
    msgs = [_make_msg(i) for i in range(1, 4)]
    count = await MessageRepository.bulk_create(db_session, msgs, source_in_db.id)
    assert count == 3


async def test_bulk_create_empty_list(db_session, source_in_db):
    count = await MessageRepository.bulk_create(db_session, [], source_in_db.id)
    assert count == 0
