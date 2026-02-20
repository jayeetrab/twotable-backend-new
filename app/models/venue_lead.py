from datetime import datetime, timezone
from typing import Optional
import enum

from sqlalchemy import String, DateTime, Text, Enum as SAEnum, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VenueLeadStatus(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    approved = "approved"
    rejected = "rejected"


class VenueLead(Base):
    __tablename__ = "venue_leads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Basic info
    venue_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Location
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Venue details
    seating_capacity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cuisine: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vibes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Availability preferences
    preferred_days: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    preferred_time_slots: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Admin
    status: Mapped[VenueLeadStatus] = mapped_column(
        SAEnum(VenueLeadStatus, name="venue_lead_status"),
        default=VenueLeadStatus.new,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
