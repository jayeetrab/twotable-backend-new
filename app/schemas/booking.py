from __future__ import annotations

from datetime import date as date_type, time as time_type
from typing import Optional
from pydantic import BaseModel


class MatchCreate(BaseModel):
    venue_id: int
    slot_id:  int
    city:     str
    date:     date_type
    time:     time_type
    mood:     Optional[str] = None
    stage:    Optional[str] = None


class BookingCreate(BaseModel):
    match_id: int
    venue_id: int
    slot_id:  int
    date:     date_type
    time:     time_type


class BookingRead(BaseModel):
    id:                       int
    match_id:                 int
    venue_id:                 Optional[int]
    slot_id:                  Optional[int]
    status:                   str
    stripe_payment_intent_id: Optional[str]
    deposit_amount_pence:     int
    booked_date:              str
    booked_time:              str

    model_config = {"from_attributes": True}


class MatchRead(BaseModel):
    id:        int
    user_a_id: int
    user_b_id: Optional[int]
    venue_id:  Optional[int]
    slot_id:   Optional[int]
    status:    str
    city:      str
    date:      str
    time:      str
    mood:      Optional[str]
    stage:     Optional[str]
    bookings:  list[BookingRead] = []

    model_config = {"from_attributes": True}
