from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, HttpUrl

from app.models.venue_lead import VenueLeadStatus


class VenueLeadCreate(BaseModel):
    # Basic info
    venue_name: str
    contact_name: str
    email: EmailStr
    phone: Optional[str] = None
    website: Optional[str] = None

    # Location
    address: str
    city: str

    # Venue details
    seating_capacity: Optional[int] = None
    cuisine: Optional[str] = None
    vibes: Optional[str] = None
    notes: Optional[str] = None

    # Availability preferences
    preferred_days: Optional[str] = None
    preferred_time_slots: Optional[str] = None


class VenueLeadRead(BaseModel):
    id: int
    venue_name: str
    contact_name: str
    email: EmailStr
    phone: Optional[str]
    website: Optional[str]
    address: str
    city: str
    seating_capacity: Optional[int]
    cuisine: Optional[str]
    vibes: Optional[str]
    notes: Optional[str]
    preferred_days: Optional[str]
    preferred_time_slots: Optional[str]
    status: VenueLeadStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VenueLeadStatusUpdate(BaseModel):
    status: VenueLeadStatus
