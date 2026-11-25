from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawMessage:
    """Raw message received from Telethon event before DB processing."""
    tg_message_id: int
    source_url: str
    text: str
    tg_date: datetime
    sender_id: int | None = None
    sender_name: str = ""
    sender_username: str | None = None
    sender_bio: str | None = None
    forward_from_chat_id: int | None = None
