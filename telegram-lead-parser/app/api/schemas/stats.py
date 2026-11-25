from datetime import datetime

from pydantic import BaseModel


class StatsResponse(BaseModel):
    total_sources: int
    active_sources: int
    total_messages: int
    scored_messages: int
    total_leads: int
    leads_by_status: dict[str, int]
    leads_by_score: dict[str, int]
    last_parse_at: datetime | None
    last_score_at: datetime | None
    listener_status: str = "unknown"
    listener_sources_count: int = 0
    listener_last_heartbeat_at: int | None = None
    messages_today: int = 0
    scored_today: int = 0
    leads_today: int = 0


class SourceStats(BaseModel):
    id: int
    name: str
    url: str
    total_messages: int
    scored_messages: int
    leads_found: int
    last_parsed_at: datetime | None
    messages_today: int = 0
    scored_today: int = 0
    leads_today: int = 0
