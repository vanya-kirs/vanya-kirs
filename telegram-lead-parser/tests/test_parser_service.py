from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.parser.schemas import MessageData, ParseResult
from app.parser.service import ParserService


def _make_msg(n: int) -> MessageData:
    return MessageData(
        tg_message_id=n,
        text=f"Message {n}",
        tg_date=datetime.now(timezone.utc),
        sender_id=100 + n,
        sender_name="Test User",
        sender_username=None,
    )


@pytest.fixture
def mock_source():
    src = MagicMock()
    src.id = 1
    src.url = "@testgroup"
    src.name = "Test Group"
    src.requires_join = False
    src.last_tg_message_id = 0
    src.last_parsed_at = None
    src.parse_interval_minutes = 15
    return src


async def test_parse_source_returns_parse_result(mock_source):
    messages = [_make_msg(i) for i in range(3)]

    with (
        patch("app.parser.service.SourceRepository") as MockSourceRepo,
        patch("app.parser.service.MessageRepository") as MockMsgRepo,
        patch("app.parser.service.TelethonClient") as MockClient,
        patch("app.parser.service.get_settings"),
        patch("app.parser.service.AsyncSessionLocal") as MockSession,
        patch("app.parser.service.ParserRateLimiter") as MockLimiter,
    ):
        mock_db = AsyncMock()
        MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

        MockSourceRepo.get_by_id = AsyncMock(return_value=mock_source)

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.scrape_messages = AsyncMock(return_value=messages)
        MockClient.return_value = mock_client_instance

        MockMsgRepo.exists = AsyncMock(return_value=False)
        MockMsgRepo.bulk_create = AsyncMock(return_value=3)
        MockSourceRepo.update_last_parsed = AsyncMock()
        MockSourceRepo.update_parse_interval = AsyncMock()
        MockLimiter.return_value = AsyncMock()

        service = ParserService()
        result = await service.parse_source(source_id=1)

    assert isinstance(result, ParseResult)
    assert result.source_id == 1
    assert result.parsed == 3
    assert result.new == 3
    assert result.skipped == 0


async def test_parse_source_raises_when_source_not_found():
    with (
        patch("app.parser.service.SourceRepository") as MockSourceRepo,
        patch("app.parser.service.AsyncSessionLocal") as MockSession,
        patch("app.parser.service.ParserRateLimiter") as MockLimiter,
        patch("app.parser.service.get_settings"),
    ):
        mock_db = AsyncMock()
        MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)
        MockSourceRepo.get_by_id = AsyncMock(return_value=None)
        MockLimiter.return_value = AsyncMock()

        service = ParserService()
        with pytest.raises(ValueError, match="Source 999 not found"):
            await service.parse_source(source_id=999)


async def test_parse_source_counts_skipped(mock_source):
    messages = [_make_msg(i) for i in range(3)]

    with (
        patch("app.parser.service.SourceRepository") as MockSourceRepo,
        patch("app.parser.service.MessageRepository") as MockMsgRepo,
        patch("app.parser.service.TelethonClient") as MockClient,
        patch("app.parser.service.get_settings"),
        patch("app.parser.service.AsyncSessionLocal") as MockSession,
        patch("app.parser.service.ParserRateLimiter") as MockLimiter,
    ):
        mock_db = AsyncMock()
        MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

        MockSourceRepo.get_by_id = AsyncMock(return_value=mock_source)

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.scrape_messages = AsyncMock(return_value=messages)
        MockClient.return_value = mock_client_instance

        # First message already exists (duplicate)
        MockMsgRepo.exists = AsyncMock(side_effect=[True, False, False])
        MockMsgRepo.bulk_create = AsyncMock(return_value=2)
        MockSourceRepo.update_last_parsed = AsyncMock()
        MockSourceRepo.update_parse_interval = AsyncMock()
        MockLimiter.return_value = AsyncMock()

        service = ParserService()
        result = await service.parse_source(source_id=1)

    assert result.parsed == 3
    assert result.new == 2
    assert result.skipped == 1


async def test_parse_source_queues_on_channel_private_error(mock_source):
    from telethon.errors import ChannelPrivateError

    mock_source.requires_join = False
    mock_source.last_tg_message_id = 0

    with (
        patch("app.parser.service.SourceRepository") as MockSourceRepo,
        patch("app.parser.service.MessageRepository"),
        patch("app.parser.service.TelethonClient") as MockClient,
        patch("app.parser.service.get_settings"),
        patch("app.parser.service.AsyncSessionLocal") as MockSession,
        patch("app.parser.service.ParserRateLimiter") as MockLimiter,
    ):
        mock_db = AsyncMock()
        MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)
        MockSourceRepo.get_by_id = AsyncMock(return_value=mock_source)
        MockSourceRepo.update_join_fields = AsyncMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.scrape_messages = AsyncMock(
            side_effect=ChannelPrivateError(request=None)
        )
        MockClient.return_value = mock_client_instance

        mock_limiter = AsyncMock()
        mock_limiter.enqueue_join = AsyncMock()
        MockLimiter.return_value = mock_limiter

        service = ParserService()
        result = await service.parse_source(source_id=1)

    assert result.queued is True
    assert result.parsed == 0
    mock_limiter.enqueue_join.assert_called_once_with(source_id=1, priority=50)


async def test_parse_source_join_limited(mock_source):
    mock_source.requires_join = True
    mock_source.last_tg_message_id = 0

    with (
        patch("app.parser.service.SourceRepository") as MockSourceRepo,
        patch("app.parser.service.AsyncSessionLocal") as MockSession,
        patch("app.parser.service.ParserRateLimiter") as MockLimiter,
        patch("app.parser.service.get_settings"),
    ):
        mock_db = AsyncMock()
        MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)
        MockSourceRepo.get_by_id = AsyncMock(return_value=mock_source)

        mock_limiter = AsyncMock()
        mock_limiter.can_join = AsyncMock(return_value=False)
        mock_limiter.get_join_count = AsyncMock(return_value=5)
        MockLimiter.return_value = mock_limiter

        service = ParserService()
        result = await service.parse_source(source_id=1)

    assert result.join_limited is True
    assert result.parsed == 0


async def test_parse_source_propagates_banned_error(mock_source):
    from app.parser.exceptions import BannedError

    mock_source.requires_join = False
    mock_source.last_tg_message_id = 0

    with (
        patch("app.parser.service.SourceRepository") as MockSourceRepo,
        patch("app.parser.service.TelethonClient") as MockClient,
        patch("app.parser.service.get_settings"),
        patch("app.parser.service.AsyncSessionLocal") as MockSession,
        patch("app.parser.service.ParserRateLimiter") as MockLimiter,
    ):
        mock_db = AsyncMock()
        MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)
        MockSourceRepo.get_by_id = AsyncMock(return_value=mock_source)

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.scrape_messages = AsyncMock(
            side_effect=BannedError("banned")
        )
        MockClient.return_value = mock_client_instance
        MockLimiter.return_value = AsyncMock()

        service = ParserService()
        with pytest.raises(BannedError):
            await service.parse_source(source_id=1)
