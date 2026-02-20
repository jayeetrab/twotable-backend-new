from datetime import datetime, time, date
from typing import Optional
from pydantic import BaseModel, EmailStr

from app.models.venue import PriceBand, NoiseLevel


class VenueSlotCreate(BaseModel):
    weekday: int
    start_time: time
    end_time: time
    max_tables_for_two: int = 2
    is_quiet_slot: bool = False


class VenueSlotRead(VenueSlotCreate):
    id: int
    venue_id: int
    is_active: bool
    model_config = {"from_attributes": True}


class VenueBlackoutCreate(BaseModel):
    start_date: date
    end_date: date
    reason: Optional[str] = None


class VenueBlackoutRead(VenueBlackoutCreate):
    id: int
    venue_id: int
    model_config = {"from_attributes": True}


class VenueCreate(BaseModel):
    name: str
    email: Optional[str] = None 
    phone: Optional[str] = None
    website: Optional[str] = None
    address: str
    city: str
    country: str = "UK"
    postcode: Optional[str] = None
    cuisine: Optional[str] = None
    vibe_tags: Optional[str] = None
    description: Optional[str] = None
    noise_level: Optional[NoiseLevel] = None
    price_band: Optional[PriceBand] = None
    total_capacity: Optional[int] = None


class VenueUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postcode: Optional[str] = None
    cuisine: Optional[str] = None
    vibe_tags: Optional[str] = None
    description: Optional[str] = None
    noise_level: Optional[NoiseLevel] = None
    price_band: Optional[PriceBand] = None
    total_capacity: Optional[int] = None
    is_active: Optional[bool] = None


class VenueRead(BaseModel):
    id: int
    name: str
    email: Optional[str] = None 
    phone: Optional[str]
    website: Optional[str]
    address: str
    city: str
    country: str
    postcode: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    cuisine: Optional[str]
    vibe_tags: Optional[str]
    description: Optional[str]
    noise_level: Optional[NoiseLevel]
    price_band: Optional[PriceBand]
    total_capacity: Optional[int]
    is_active: bool
    created_at: datetime
    slots: list[VenueSlotRead] = []
    blackouts: list[VenueBlackoutRead] = []
    model_config = {"from_attributes": True}


class VenuePromoteRequest(BaseModel):
    noise_level: Optional[NoiseLevel] = None
    price_band: Optional[PriceBand] = None
    description: Optional[str] = None
    vibe_tags: Optional[str] = None
    postcode: Optional[str] = None
