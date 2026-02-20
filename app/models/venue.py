from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base  # ← fixed

if TYPE_CHECKING:
    from app.models.venue_slot import VenueSlot
    from app.models.venue_blackout import VenueBlackout
    from app.models.venue_embedding import VenueEmbedding


class PriceBand(str, enum.Enum):
    budget = "budget"
    mid = "mid"
    premium = "premium"
    luxury = "luxury"


class NoiseLevel(str, enum.Enum):
    quiet = "quiet"
    moderate = "moderate"
    lively = "lively"
    loud = "loud"


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    lead_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("venue_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    address: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(100), default="UK", nullable=False)
    postcode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    cuisine: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Stored as comma-separated string e.g. "cosy,romantic,candlelit"
    vibe_tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    noise_level: Mapped[Optional[NoiseLevel]] = mapped_column(
        SAEnum(NoiseLevel, name="noise_level"), nullable=True
    )
    price_band: Mapped[Optional[PriceBand]] = mapped_column(
        SAEnum(PriceBand, name="price_band"), nullable=True
    )

    total_capacity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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

    slots: Mapped[list[VenueSlot]] = relationship(
        "VenueSlot", back_populates="venue", cascade="all, delete-orphan"
    )
    blackouts: Mapped[list[VenueBlackout]] = relationship(
        "VenueBlackout", back_populates="venue", cascade="all, delete-orphan"
    )
    # ── Step 7: one-to-one embedding ──────────────────────────────────────────
    embedding: Mapped[Optional[VenueEmbedding]] = relationship(
        "VenueEmbedding",
        back_populates="venue",
        uselist=False,
        cascade="all, delete-orphan",
    )
