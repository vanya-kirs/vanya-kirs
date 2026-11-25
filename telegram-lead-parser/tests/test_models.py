from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, User, Source, Message


# Use in-memory SQLite for model unit tests (no async needed for schema checks)
@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def test_user_model_creation(session):
    user = User(telegram_id=123456789, username="testuser", is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)

    assert user.id is not None
    assert user.telegram_id == 123456789
    assert user.username == "testuser"
    assert user.is_active is True
    assert user.created_at is not None
    assert user.updated_at is not None


def test_user_username_nullable(session):
    user = User(telegram_id=999, username=None, is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.username is None


def test_source_model_creation(session):
    user = User(telegram_id=111, username="owner")
    session.add(user)
    session.flush()

    source = Source(
        url="https://t.me/test_channel",
        name="Test Channel",
        user_id=user.id,
        is_active=True,
    )
    session.add(source)
    session.commit()
    session.refresh(source)

    assert source.id is not None
    assert source.url == "https://t.me/test_channel"
    assert source.user_id == user.id
    assert source.last_parsed_at is None


def test_source_user_relationship(session):
    user = User(telegram_id=222, username="rel_owner")
    session.add(user)
    session.flush()

    source = Source(url="https://t.me/rel_ch", name="Rel Ch", user_id=user.id)
    session.add(source)
    session.commit()
    session.refresh(source)

    assert source.user.telegram_id == 222


def test_message_model_creation(session):
    user = User(telegram_id=333, username="msg_owner")
    session.add(user)
    session.flush()

    source = Source(url="https://t.me/msg_ch", name="Msg Ch", user_id=user.id)
    session.add(source)
    session.flush()

    now = datetime.now(timezone.utc)
    msg = Message(
        source_id=source.id,
        sender_id=987654321,
        sender_username="sender",
        sender_name="John Doe",
        sender_bio="Some bio",
        text="Hello lead!",
        tg_message_id=42,
        tg_date=now,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)

    assert msg.id is not None
    assert msg.source_id == source.id
    assert msg.text == "Hello lead!"
    assert msg.tg_message_id == 42


def test_message_source_relationship(session):
    user = User(telegram_id=444, username="rel2_owner")
    session.add(user)
    session.flush()

    source = Source(url="https://t.me/rel2_ch", name="Rel2 Ch", user_id=user.id)
    session.add(source)
    session.flush()

    now = datetime.now(timezone.utc)
    msg = Message(
        source_id=source.id,
        tg_message_id=1,
        tg_date=now,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)

    assert msg.source.name == "Rel2 Ch"


def test_message_nullable_fields(session):
    user = User(telegram_id=555)
    session.add(user)
    session.flush()

    source = Source(url="https://t.me/null_ch", name="Null Ch", user_id=user.id)
    session.add(source)
    session.flush()

    now = datetime.now(timezone.utc)
    msg = Message(source_id=source.id, tg_message_id=99, tg_date=now)
    session.add(msg)
    session.commit()
    session.refresh(msg)

    assert msg.sender_id is None
    assert msg.sender_username is None
    assert msg.text is None
    assert msg.sender_bio is None
