from datetime import datetime

from pydantic import BaseModel


class ProfileResponse(BaseModel):
    id: int
    telegram_id: int | None
    username: str | None
    subscription_until: datetime | None
    parsing_enabled: bool
    subscription_active: bool

    model_config = {"from_attributes": True}


class ParseToggleRequest(BaseModel):
    enabled: bool
