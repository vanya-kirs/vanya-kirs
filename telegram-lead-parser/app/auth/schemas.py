from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr = Field(example="user@example.com")
    password: str = Field(min_length=8, example="strongpassword123")
    username: str | None = Field(default=None, max_length=100, example="myusername")


class LoginRequest(BaseModel):
    email: EmailStr = Field(example="user@example.com")
    password: str = Field(example="strongpassword123")


class BotLoginRequest(BaseModel):
    telegram_id: int
    bot_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str = Field(example="eyJhbGci...")


class UserResponse(BaseModel):
    id: int
    email: str | None
    username: str | None
    is_active: bool

    model_config = {"from_attributes": True}
