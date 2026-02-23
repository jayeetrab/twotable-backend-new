from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserSocialSignal(Base):
    __tablename__ = "user_social_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # e.g. "instagram", "spotify"
    platform: Mapped[str] = mapped_column(String(40), nullable=False)

    # e.g. "music_genre", "aesthetic", "activity", "personality_trait",
    #       "valence", "energy_level", "tempo_preference"
    signal_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)

    # e.g. "jazz", "moody dark cinematic", "hiking coffee shops", "0.82"
    signal_value: Mapped[str] = mapped_column(Text, nullable=False)

    # confidence 0.0–1.0 (set by the extraction LLM/API)
    confidence: Mapped[Optional[float]] = mapped_column(nullable=True)

    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
