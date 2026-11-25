from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tg_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tg_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_scored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    text_hash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    score_skip_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    forward_from_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source: Mapped["Source"] = relationship("Source", back_populates="messages")
    lead: Mapped["Lead | None"] = relationship("Lead", back_populates="message", uselist=False)
