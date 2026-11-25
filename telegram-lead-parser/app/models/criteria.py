from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class CriteriaProfile(Base):
    __tablename__ = "criteria_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    min_score: Mapped[int] = mapped_column(Integer, default=40, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="criteria_profiles")
    leads: Mapped[list["Lead"]] = relationship("Lead", back_populates="criteria_profile")
