from datetime import datetime

from pydantic import BaseModel, Field


class CriteriaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, example="Предприниматели (базовый)")
    description: str = Field(
        min_length=10,
        example="Предприниматели и специалисты с опытом, находящиеся в состоянии роста.",
    )
    min_score: int = Field(default=40, ge=40, le=80, example=40)


class CriteriaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=10)
    min_score: int | None = Field(default=None, ge=0, le=100)


class MinScoreUpdate(BaseModel):
    min_score: int = Field(ge=40, le=80)


class CriteriaResponse(BaseModel):
    id: int
    name: str
    description: str
    min_score: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
