from dataclasses import dataclass
from datetime import datetime


@dataclass
class MessageData:
    tg_message_id: int
    text: str
    tg_date: datetime
    sender_id: int | None
    sender_name: str
    sender_username: str | None
    sender_bio: str | None = None
    forward_from_chat_id: int | None = None


@dataclass
class UserProfile:
    id: int
    first_name: str
    last_name: str | None
    username: str | None
    bio: str | None
    phone: str | None


@dataclass
class ParseResult:
    source_id: int
    parsed: int
    new: int
    skipped: int
    duration_seconds: float
    queued: bool = False
    join_limited: bool = False
    renamed: bool = False
    lost: bool = False


@dataclass
class GlobalSearchResult:
    chat_id: int
    chat_username: str | None
    chat_title: str | None
    chat_members: int | None
    message_id: int
    message_text: str
    message_date: datetime


@dataclass
class SourceValidation:
    is_valid: bool
    title: str | None
    members_count: int | None
    error: str | None
    tg_channel_id: int | None = None
    tg_access_hash: int | None = None
