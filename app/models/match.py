from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.booking import Booking


class MatchStatus(str, enum.Enum):
    pending   = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_a_id: Mapped[int]           = mapped_column(Integer, ForeignKey("users.id",       ondelete="CASCADE"),  nullable=False)
    user_b_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id",       ondelete="CASCADE"),  nullable=True)
    venue_id:  Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("venues.id",      ondelete="SET NULL"), nullable=True)
    slot_id:   Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("venue_slots.id", ondelete="SET NULL"), nullable=True)

    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, name="matchstatus"),
        default=MatchStatus.pending,
        nullable=False,
    )

    city:  Mapped[str]           = mapped_column(String(120), nullable=False)
    date:  Mapped[str]           = mapped_column(String(20),  nullable=False)  # ISO date
    time:  Mapped[str]           = mapped_column(String(10),  nullable=False)  # HH:MM
    mood:  Mapped[Optional[str]] = mapped_column(String(60),  nullable=True)
    stage: Mapped[Optional[str]] = mapped_column(String(60),  nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # String ref avoids circular import at runtime
    bookings: Mapped[List["Booking"]] = relationship(
        "Booking",
        back_populates="match",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
