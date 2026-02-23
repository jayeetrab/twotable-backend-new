from __future__ import annotations

import enum
from datetime import date, datetime, time
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.user_profile import (
    AlcoholPreference,
    CommunicationStyle,
    Gender,
    PreferredTime,
    RelationshipGoal,
    RelationshipStagePref,
    SocialEnergy,
)

# ── Allowed value constants ───────────────────────────────────────────────────

VALID_LOVE_LANGUAGES  = {"words", "acts", "gifts", "time", "touch"}
VALID_MOODS           = {"romantic", "cosy", "buzzy", "adventurous", "chill"}
VALID_BUDGETS         = {"budget", "mid", "premium", "luxury"}
VALID_NOISE           = {"quiet", "moderate", "lively", "loud"}
VALID_GENDERS         = {g.value for g in Gender}


# ── Onboarding answers ────────────────────────────────────────────────────────

class OnboardingAnswers(BaseModel):
    """Structured answers to the 5 onboarding questions."""
    ideal_first_date:        Optional[str] = Field(None, max_length=150,
        description="Describe your ideal first date in 3 words")
    dealbreaker:             Optional[str] = Field(None, max_length=200,
        description="What's a dealbreaker for you?")
    values_in_partner:       Optional[str] = Field(None, max_length=200,
        description="What do you value most in a partner?")
    planner_or_spontaneous:  Optional[Literal["planner", "spontaneous", "mix"]] = Field(None,
        description="Are you more of a planner or spontaneous?")
    last_laugh:              Optional[str] = Field(None, max_length=300,
        description="What was the last thing that made you genuinely laugh?")


# ── Availability ──────────────────────────────────────────────────────────────

class AvailabilitySlotCreate(BaseModel):
    weekday:    int  = Field(..., ge=0, le=6, description="0=Monday … 6=Sunday")
    start_time: time = Field(..., description="HH:MM:SS")
    end_time:   time = Field(..., description="HH:MM:SS")

    @model_validator(mode="after")
    def end_after_start(self) -> "AvailabilitySlotCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class AvailabilitySlotRead(BaseModel):
    id:         int
    user_id:    int
    weekday:    int
    start_time: time
    end_time:   time

    model_config = {"from_attributes": True}


class AvailabilitySetRequest(BaseModel):
    """Full-replace payload: supply all slots for the coming week."""
    slots: List[AvailabilitySlotCreate] = Field(
        ..., min_length=1, max_length=21,
        description="Up to 21 availability windows (3 per day max)"
    )


# ── Profile setup / update ────────────────────────────────────────────────────

class ProfileSetupRequest(BaseModel):
    """
    Upsert payload for POST /profile/setup.
    All fields are optional — supply only what changed.
    On first call, supply as many as possible to set profile_complete=True.
    """
    # Core identity
    date_of_birth:      Optional[date]                    = None
    gender:             Optional[Gender]                  = None
    looking_for_gender: Optional[List[str]]               = None
    city:               Optional[str]                     = Field(None, max_length=120)
    home_lat:           Optional[float]                   = None
    home_lng:           Optional[float]                   = None
    max_travel_km:      Optional[int]                     = Field(None, ge=1, le=200)
    profile_photo_url:  Optional[str]                     = Field(None, max_length=500)

    # Relationship intent
    relationship_goal:        Optional[RelationshipGoal]       = None
    relationship_stage_pref:  Optional[RelationshipStagePref]  = None

    # Personality
    social_energy:        Optional[SocialEnergy]       = None
    communication_style:  Optional[CommunicationStyle] = None
    love_language:        Optional[List[str]]           = None

    # Date preferences
    preferred_mood:       Optional[str]                = None
    preferred_budget:     Optional[str]                = None
    preferred_time:       Optional[PreferredTime]      = None
    alcohol:              Optional[AlcoholPreference]  = None
    dietary_requirements: Optional[str]                = Field(None, max_length=255)
    noise_tolerance:      Optional[str]                = None

    # Interests
    music_genres:         Optional[List[str]] = None
    cuisine_preferences:  Optional[List[str]] = None
    activities:           Optional[List[str]] = None
    hobbies:              Optional[List[str]] = None

    # Bio
    bio:      Optional[str] = Field(None, max_length=300)
    fun_fact: Optional[str] = Field(None, max_length=150)

    # Onboarding
    onboarding_answers: Optional[OnboardingAnswers] = None

    # ── Field-level validators ────────────────────────────────────────────────

    @field_validator("preferred_mood")
    @classmethod
    def validate_mood(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_MOODS:
            raise ValueError(f"preferred_mood must be one of {sorted(VALID_MOODS)}")
        return v

    @field_validator("preferred_budget")
    @classmethod
    def validate_budget(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_BUDGETS:
            raise ValueError(f"preferred_budget must be one of {sorted(VALID_BUDGETS)}")
        return v

    @field_validator("noise_tolerance")
    @classmethod
    def validate_noise(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_NOISE:
            raise ValueError(f"noise_tolerance must be one of {sorted(VALID_NOISE)}")
        return v

    @field_validator("looking_for_gender")
    @classmethod
    def validate_looking_for(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            invalid = set(v) - VALID_GENDERS
            if invalid:
                raise ValueError(f"Invalid gender values: {invalid}. Must be from {sorted(VALID_GENDERS)}")
        return v

    @field_validator("love_language")
    @classmethod
    def validate_love_language(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            invalid = set(v) - VALID_LOVE_LANGUAGES
            if invalid:
                raise ValueError(f"Invalid love_language values: {invalid}. Must be from {sorted(VALID_LOVE_LANGUAGES)}")
        return v


# ── Profile read ──────────────────────────────────────────────────────────────

class ProfileRead(BaseModel):
    """Serialised UserProfile row."""
    id:                      int
    user_id:                 int
    date_of_birth:           Optional[date]
    gender:                  Optional[Gender]
    looking_for_gender:      Optional[Any]
    city:                    Optional[str]
    home_lat:                Optional[float]
    home_lng:                Optional[float]
    max_travel_km:           Optional[int]
    profile_photo_url:       Optional[str]
    relationship_goal:       Optional[RelationshipGoal]
    relationship_stage_pref: Optional[RelationshipStagePref]
    social_energy:           Optional[SocialEnergy]
    communication_style:     Optional[CommunicationStyle]
    love_language:           Optional[Any]
    preferred_mood:          Optional[str]
    preferred_budget:        Optional[str]
    preferred_time:          Optional[PreferredTime]
    alcohol:                 Optional[AlcoholPreference]
    dietary_requirements:    Optional[str]
    noise_tolerance:         Optional[str]
    music_genres:            Optional[Any]
    cuisine_preferences:     Optional[Any]
    activities:              Optional[Any]
    hobbies:                 Optional[Any]
    bio:                     Optional[str]
    fun_fact:                Optional[str]
    onboarding_answers:      Optional[Any]
    profile_complete:        bool
    created_at:              datetime
    updated_at:              datetime

    model_config = {"from_attributes": True}


class FullProfileRead(BaseModel):
    """
    Composite response for GET /profile/me.
    Combines the User base record + UserProfile + availability slots.
    """
    id:           int
    email:        str
    full_name:    Optional[str]
    role:         str
    is_active:    bool
    profile:      Optional[ProfileRead]           = None
    availability: List[AvailabilitySlotRead]      = []

    model_config = {"from_attributes": True}
# ── Social connect request ────────────────────────────────────────────────────

class SocialConnectRequest(BaseModel):
    access_token:       str
    refresh_token:      Optional[str] = None
    platform_user_id:   Optional[str] = None
    platform_username:  Optional[str] = None


# ── Social connection read ────────────────────────────────────────────────────

class SocialConnectionRead(BaseModel):
    id:                 int
    user_id:            int
    platform:           str
    platform_username:  Optional[str]
    connected_at:       datetime
    last_synced_at:     Optional[datetime]
    is_active:          bool

    model_config = {"from_attributes": True}


# ── Social signal read ────────────────────────────────────────────────────────

class SocialSignalRead(BaseModel):
    id:           int
    user_id:      int
    platform:     str
    signal_type:  str
    signal_value: str
    confidence:   Optional[float]
    extracted_at: datetime

    model_config = {"from_attributes": True}
