from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, DateTime, Float, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class GeocodingCache(Base):
    __tablename__ = "geocoding_cache"
    __table_args__ = (
        UniqueConstraint("raw_query", "provider", name="uq_geocoding_cache_query_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_query: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    formatted_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
