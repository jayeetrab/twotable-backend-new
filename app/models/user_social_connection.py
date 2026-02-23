from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SocialPlatform(str, enum.Enum):
    instagram = "instagram"
    spotify   = "spotify"


class UserSocialConnection(Base):
    __tablename__ = "user_social_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[SocialPlatform] = mapped_column(
        SAEnum(SocialPlatform, name="social_platform_enum", create_type=True),
        nullable=False,
    )
    access_token:  Mapped[Optional[str]] = mapped_column(Text,        nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text,        nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    platform_user_id:   Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    platform_username:  Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
