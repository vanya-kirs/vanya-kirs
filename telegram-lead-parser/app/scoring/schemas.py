from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MessageToScore:
    message_id: int
    text: str
    sender_name: str
    sender_username: str | None
    sender_bio: str | None
    source_url: str


@dataclass
class ScoringResult:
    message_id: int
    fit: bool
    score: int
    reason: str
    signals: list[str]
    raw_response: dict
    scored_at: datetime
    error: str | None = None


@dataclass
class ScoringBatchResult:
    total: int
    scored: int
    leads_found: int
    errors: int
    duration_seconds: float
