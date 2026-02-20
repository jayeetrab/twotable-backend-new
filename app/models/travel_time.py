from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class TravelTimeCache(Base):
    __tablename__ = "travel_time_cache"
    __table_args__ = (
        UniqueConstraint(
            "origin_hash", "venue_id", "mode", "time_bucket",
            name="uq_travel_time_cache"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    origin_hash: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(20), default="drive", nullable=False)
    time_bucket: Mapped[str] = mapped_column(String(30), nullable=False)
    travel_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
