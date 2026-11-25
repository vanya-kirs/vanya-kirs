from pydantic import BaseModel, Field


class ParseRunRequest(BaseModel):
    source_id: int = Field(example=1)


class ParseRunResponse(BaseModel):
    task_id: str
    source_id: int
    status: str = "queued"
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # pending / started / success / failure
    result: dict | None = None
    error: str | None = None
