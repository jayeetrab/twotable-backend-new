from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base  # ← fixed

if TYPE_CHECKING:
    from app.models.venue import Venue


class VenueBlackout(Base):
    __tablename__ = "venue_blackouts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Single day blackout — used by availability filter
    # For multi-day ranges: start_date = first day, end_date = last day (inclusive)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    venue: Mapped[Venue] = relationship("Venue", back_populates="blackouts")
