from __future__ import annotations

from datetime import date as date_type, time as time_type
from typing import Optional, List
from pydantic import BaseModel, Field
import enum


class RelationshipStage(str, enum.Enum):
    first_date = "first_date"
    second_third = "second_third"
    together = "together"


class Mood(str, enum.Enum):
    romantic = "romantic"
    cosy = "cosy"
    buzzy = "buzzy"
    adventurous = "adventurous"
    chill = "chill"


class EnergyLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class BudgetBand(str, enum.Enum):
    budget = "budget"
    mid = "mid"
    premium = "premium"
    luxury = "luxury"


class TravelMode(str, enum.Enum):
    drive = "drive"
    walk = "walk"
    transit = "transit"


class SuggestRequest(BaseModel):
    city: str = Field(..., examples=["Bristol"])
    origin_lat: Optional[float] = Field(None, examples=[51.4545])
    origin_lng: Optional[float] = Field(None, examples=[-2.5879])
    travel_mode: TravelMode = TravelMode.drive
    max_travel_minutes: int = Field(45, ge=5, le=45)
    date: date_type = Field(..., examples=["2026-02-25"])
    time: time_type = Field(..., examples=["19:00:00"])
    stage: RelationshipStage = RelationshipStage.first_date
    mood: Mood = Mood.romantic
    energy: EnergyLevel = EnergyLevel.low
    budget: BudgetBand = BudgetBand.mid
    free_text: Optional[str] = Field(None, max_length=300)
    top_n: int = Field(3, ge=1, le=10)
    session_id: Optional[str] = None


class VenueSuggestion(BaseModel):
    venue_id: int
    name: str
    address: str
    city: str
    cuisine: Optional[str]
    vibe_tags: Optional[str]
    noise_level: Optional[str]
    price_band: Optional[str]
    description: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    travel_minutes: Optional[float]
    similarity_score: float
    load_factor: float
    final_score: float
    source_text: Optional[str] = None


class SuggestResponse(BaseModel):
    count: int
    intent_text: str
    suggestions: List[VenueSuggestion]
