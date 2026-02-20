from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.match import Match


class BookingStatus(str, enum.Enum):
    pending   = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    refunded  = "refunded"


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    match_id: Mapped[int]           = mapped_column(Integer, ForeignKey("matches.id",      ondelete="CASCADE"),  nullable=False)
    venue_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("venues.id",       ondelete="SET NULL"), nullable=True)
    slot_id:  Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("venue_slots.id",  ondelete="SET NULL"), nullable=True)

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="bookingstatus"),
        default=BookingStatus.pending,
        nullable=False,
    )

    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    deposit_amount_pence:     Mapped[int]            = mapped_column(Integer, default=1000)  # £10.00

    booked_date: Mapped[str] = mapped_column(String(20), nullable=False)  # ISO date
    booked_time: Mapped[str] = mapped_column(String(10), nullable=False)  # HH:MM

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
    match: Mapped["Match"] = relationship(
        "Match",
        back_populates="bookings",
        lazy="selectin",
    )
