from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("message_id", name="uq_leads_message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    criteria_profile_id: Mapped[int] = mapped_column(
        ForeignKey("criteria_profiles.id"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    fit: Mapped[bool] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    signals: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    raw_response: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="new"
    )  # new / viewed / contacted / rejected
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    message: Mapped["Message"] = relationship("Message", back_populates="lead")
    criteria_profile: Mapped["CriteriaProfile"] = relationship(
        "CriteriaProfile", back_populates="leads"
    )
