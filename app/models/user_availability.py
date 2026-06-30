from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserAvailability(Base):
    __tablename__ = "user_availability"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "weekday", "start_time",
            name="uq_user_availability_slot",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 0 = Monday … 6 = Sunday  (ISO weekday - 1)
    weekday:    Mapped[int]  = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time,    nullable=False)
    end_time:   Mapped[time] = mapped_column(Time,    nullable=False)

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

