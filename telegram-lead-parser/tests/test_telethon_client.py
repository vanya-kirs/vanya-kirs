from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.parser.client import TelethonClient
from app.parser.schemas import MessageData, SourceValidation, UserProfile


@pytest.fixture
def client():
    return TelethonClient(api_id=12345, api_hash="abc", session_string="sess")


async def test_context_manager_connects_and_disconnects(client):
    with patch.object(client, "_client") as mock_tg:
        mock_tg.connect = AsyncMock()
        mock_tg.disconnect = AsyncMock()
        async with client:
            mock_tg.connect.assert_called_once()
        mock_tg.disconnect.assert_called_once()


async def test_scrape_messages_returns_message_data(client):
    mock_msg = MagicMock()
    mock_msg.id = 1
    mock_msg.message = "Buy now!"
    mock_msg.date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_msg.sender_id = 42

    mock_sender = MagicMock()
    mock_sender.first_name = "Ivan"
    mock_sender.last_name = "Petrov"
    mock_sender.username = "ivanp"

    async def fake_get_sender():
        return mock_sender

    mock_msg.get_sender = fake_get_sender
    mock_msg.sender = mock_sender

    async def fake_iter_messages(*args, **kwargs):
        yield mock_msg

    with patch.object(client, "_client") as mock_tg:
        mock_tg.iter_messages = fake_iter_messages
        with patch("asyncio.sleep", new_callable=AsyncMock):
            results = await client.scrape_messages("@testgroup", limit=10)

    assert len(results) == 1
    assert isinstance(results[0], MessageData)
    assert results[0].tg_message_id == 1
    assert results[0].text == "Buy now!"
    assert results[0].sender_id == 42
    assert results[0].sender_name == "Ivan Petrov"


async def test_scrape_messages_skips_empty_text(client):
    mock_msg = MagicMock()
    mock_msg.id = 5
    mock_msg.message = ""  # empty — should be skipped
    mock_msg.date = datetime(2024, 1, 1, tzinfo=timezone.utc)

    async def fake_iter_messages(*args, **kwargs):
        yield mock_msg

    with patch.object(client, "_client") as mock_tg:
        mock_tg.iter_messages = fake_iter_messages
        with patch("asyncio.sleep", new_callable=AsyncMock):
            results = await client.scrape_messages("@testgroup", limit=10)

    assert len(results) == 0


async def test_scrape_messages_handles_flood_wait(client):
    from telethon.errors import FloodWaitError

    call_count = 0

    async def fake_iter_messages(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FloodWaitError(request=None, capture=2)
        mock_msg = MagicMock()
        mock_msg.id = 1
        mock_msg.message = "text"
        mock_msg.date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_msg.sender_id = 1

        async def fake_sender():
            s = MagicMock()
            s.first_name = "X"
            s.last_name = None
            s.username = None
            return s

        mock_msg.get_sender = fake_sender
        yield mock_msg

    with patch.object(client, "_client") as mock_tg:
        mock_tg.iter_messages = fake_iter_messages
        with patch("asyncio.sleep", new_callable=AsyncMock):
            results = await client.scrape_messages("@testgroup", limit=10)

    # FloodWait returns empty list on first call (returns what was collected before error)
    assert isinstance(results, list)


async def test_validate_source_returns_validation(client):
    mock_entity = MagicMock()
    mock_entity.title = "Test Channel"
    mock_entity.participants_count = 1500

    with patch.object(client, "_client") as mock_tg:
        mock_tg.get_entity = AsyncMock(return_value=mock_entity)
        result = await client.validate_source("@testchannel")

    assert isinstance(result, SourceValidation)
    assert result.is_valid is True
    assert result.title == "Test Channel"
    assert result.members_count == 1500


async def test_validate_source_returns_invalid_on_error(client):
    from telethon.errors import UsernameNotOccupiedError

    with patch.object(client, "_client") as mock_tg:
        mock_tg.get_entity = AsyncMock(
            side_effect=UsernameNotOccupiedError(request=None)
        )
        result = await client.validate_source("@nonexistent")

    assert result.is_valid is False
    assert result.error is not None


async def test_join_channel_raises_banned_error(client):
    from telethon.errors import UserDeactivatedBanError
    from app.parser.exceptions import BannedError

    mock_tg = AsyncMock()
    mock_tg.side_effect = UserDeactivatedBanError(request=None)
    client._client = mock_tg
    with pytest.raises(BannedError):
        await client.join_channel("@testchannel")


async def test_scrape_messages_reraises_channel_private_error(client):
    from telethon.errors import ChannelPrivateError

    async def fake_iter_messages(*args, **kwargs):
        raise ChannelPrivateError(request=None)
        yield  # make it an async generator

    with patch.object(client, "_client") as mock_tg:
        mock_tg.iter_messages = fake_iter_messages
        with pytest.raises(ChannelPrivateError):
            await client.scrape_messages("@privategroup", limit=10)


async def test_scrape_messages_raises_banned_error_on_deactivated(client):
    from telethon.errors import UserDeactivatedBanError
    from app.parser.exceptions import BannedError

    async def fake_iter_messages(*args, **kwargs):
        raise UserDeactivatedBanError(request=None)
        yield

    with patch.object(client, "_client") as mock_tg:
        mock_tg.iter_messages = fake_iter_messages
        with pytest.raises(BannedError):
            await client.scrape_messages("@testgroup", limit=10)


async def test_msg_pause_is_random(client):
    """Verify asyncio.sleep is called with a value in [3.0, 8.0]."""
    mock_sender = MagicMock()
    mock_sender.first_name = "A"
    mock_sender.last_name = None
    mock_sender.username = None

    mock_msg = MagicMock()
    mock_msg.id = 1
    mock_msg.message = "text"
    mock_msg.date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_msg.sender_id = 1
    mock_msg.sender = mock_sender

    sleep_calls = []

    async def recording_sleep(seconds):
        sleep_calls.append(seconds)

    async def fake_iter(*args, **kwargs):
        yield mock_msg

    with patch.object(client, "_client") as mock_tg:
        mock_tg.iter_messages = fake_iter
        with patch("asyncio.sleep", side_effect=recording_sleep):
            await client.scrape_messages("@test", limit=1)

    assert len(sleep_calls) == 1
    assert 3.0 <= sleep_calls[0] <= 8.0
