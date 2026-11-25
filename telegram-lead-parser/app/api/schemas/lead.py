from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

VALID_STATUSES = ("new", "viewed", "contacted", "rejected")


class MessageBrief(BaseModel):
    id: int
    sender_id: int | None = None
    text: str | None = None
    sender_name: str | None = None
    sender_username: str | None = None
    sender_bio: str | None = None
    sender_phone: str | None = None
    tg_date: datetime

    model_config = {"from_attributes": True}


class SourceBrief(BaseModel):
    id: int
    url: str
    name: str

    model_config = {"from_attributes": True}


class LeadResponse(BaseModel):
    id: int
    score: int
    fit: bool
    reason: str
    signals: list[str]
    status: str
    scored_at: datetime
    message: MessageBrief
    source: SourceBrief

    model_config = {"from_attributes": True}


class LeadStatusUpdate(BaseModel):
    status: Literal["new", "viewed", "contacted", "rejected"] = Field(
        example="viewed",
        description="Lead status: new / viewed / contacted / rejected",
    )


class LeadsFilter(BaseModel):
    min_score: int | None = Field(default=None, ge=0, le=100)
    status: str | None = None
    source_id: int | None = None
    limit: int = Field(default=20, le=100)
    offset: int = Field(default=0)
