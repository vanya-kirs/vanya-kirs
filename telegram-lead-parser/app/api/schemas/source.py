from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SourceCreate(BaseModel):
    url: str = Field(example="@somegroup", description="Telegram URL: starts with @ or https://t.me/")
    name: str = Field(min_length=1, max_length=100, example="Some Group")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("@") or v.startswith("https://t.me/")):
            raise ValueError("URL must start with '@' or 'https://t.me/'")
        return v


class SourceResponse(BaseModel):
    id: int
    url: str
    name: str
    is_active: bool
    parsing_enabled: bool
    last_parsed_at: datetime | None
    created_at: datetime
    requires_join: bool = False
    join_queued_at: datetime | None = None
    discovery_method: str = "manual"
    status: str = "active"

    model_config = {"from_attributes": True}


class SourceImportItem(BaseModel):
    url: str
    name: str | None = None


class SourceImportRequest(BaseModel):
    items: list[SourceImportItem]


class SourceImportResponse(BaseModel):
    imported: int
    skipped: int
    errors: list[dict]


class SourceValidateRequest(BaseModel):
    url: str = Field(example="@somegroup")


class SourceValidateResponse(BaseModel):
    is_valid: bool
    title: str | None = None
    members_count: int | None = None
    error: str | None = None
