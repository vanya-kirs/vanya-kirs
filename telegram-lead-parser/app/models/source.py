from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parsing_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_parsed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_tg_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    requires_join: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    join_queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parse_interval_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    tg_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tg_access_hash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discovery_method: Mapped[str] = mapped_column(String(20), default="manual", nullable=False, server_default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="sources")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="source")
