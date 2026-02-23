from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Enum as SAEnum,
    Float, ForeignKey, Integer, String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Gender(str, enum.Enum):
    man        = "man"
    woman      = "woman"
    non_binary = "non_binary"
    other      = "other"


class RelationshipGoal(str, enum.Enum):
    serious   = "serious"
    casual    = "casual"
    open      = "open"
    undecided = "undecided"


class RelationshipStagePref(str, enum.Enum):
    first_date   = "first_date"
    second_third = "second_third"
    together     = "together"


class SocialEnergy(str, enum.Enum):
    introvert = "introvert"
    ambivert  = "ambivert"
    extrovert = "extrovert"


class CommunicationStyle(str, enum.Enum):
    deep_talker  = "deep_talker"
    light_banter = "light_banter"
    mix          = "mix"


class PreferredTime(str, enum.Enum):
    weekday_evenings    = "weekday_evenings"
    weekend_afternoons  = "weekend_afternoons"
    weekend_evenings    = "weekend_evenings"


class AlcoholPreference(str, enum.Enum):
    yes       = "yes"
    no        = "no"
    sometimes = "sometimes"


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # ── Core identity ─────────────────────────────────────────────────────────
    date_of_birth:     Mapped[Optional[date]]  = mapped_column(Date,         nullable=True)
    gender:            Mapped[Optional[Gender]] = mapped_column(
        SAEnum(Gender, name="gender_enum", create_type=True), nullable=True
    )
    # JSONB list of Gender values: ["man", "woman", ...]
    looking_for_gender: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    city:              Mapped[Optional[str]]   = mapped_column(String(120), nullable=True, index=True)
    home_lat:          Mapped[Optional[float]] = mapped_column(Float,        nullable=True)
    home_lng:          Mapped[Optional[float]] = mapped_column(Float,        nullable=True)
    max_travel_km:     Mapped[Optional[int]]   = mapped_column(Integer,      nullable=True)
    profile_photo_url: Mapped[Optional[str]]   = mapped_column(String(500),  nullable=True)

    # ── Relationship intent ───────────────────────────────────────────────────
    relationship_goal: Mapped[Optional[RelationshipGoal]] = mapped_column(
        SAEnum(RelationshipGoal, name="relationship_goal_enum", create_type=True), nullable=True
    )
    relationship_stage_pref: Mapped[Optional[RelationshipStagePref]] = mapped_column(
        SAEnum(RelationshipStagePref, name="relationship_stage_pref_enum", create_type=True),
        nullable=True,
    )

    # ── Personality + social style ────────────────────────────────────────────
    social_energy: Mapped[Optional[SocialEnergy]] = mapped_column(
        SAEnum(SocialEnergy, name="social_energy_enum", create_type=True), nullable=True
    )
    communication_style: Mapped[Optional[CommunicationStyle]] = mapped_column(
        SAEnum(CommunicationStyle, name="communication_style_enum", create_type=True), nullable=True
    )
    # JSONB list: ["words", "time", "touch", ...]
    love_language: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # ── Date preferences ──────────────────────────────────────────────────────
    # String — values validated at Pydantic layer to match Mood enum: romantic/cosy/buzzy/adventurous/chill
    preferred_mood:   Mapped[Optional[str]] = mapped_column(String(60),  nullable=True)
    # String — values: budget/mid/premium/luxury
    preferred_budget: Mapped[Optional[str]] = mapped_column(String(20),  nullable=True)
    preferred_time:   Mapped[Optional[PreferredTime]] = mapped_column(
        SAEnum(PreferredTime, name="preferred_time_enum", create_type=True), nullable=True
    )
    alcohol: Mapped[Optional[AlcoholPreference]] = mapped_column(
        SAEnum(AlcoholPreference, name="alcohol_preference_enum", create_type=True), nullable=True
    )
    dietary_requirements: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # String — values: quiet/moderate/lively/loud
    noise_tolerance: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # ── Interests (JSONB multi-select) ────────────────────────────────────────
    music_genres:        Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    cuisine_preferences: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    activities:          Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    hobbies:             Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # ── Bio ───────────────────────────────────────────────────────────────────
    bio:      Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    fun_fact: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    # ── Onboarding ────────────────────────────────────────────────────────────
    # JSONB dict — see OnboardingAnswers schema for structure
    onboarding_answers: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    profile_complete:   Mapped[bool]           = mapped_column(Boolean, default=False, nullable=False)

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
