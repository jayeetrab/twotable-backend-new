"""Venue domain enums. Documents live in the ``venues`` collection.

A venue document is shaped like::

    {
      "_id": 12,
      "name": "...", "email": null, "phone": "...", "website": "...",
      "address": "...", "city": "Bristol", "country": "UK", "postcode": "...",
      "lat": 51.45, "lng": -2.58,
      "cuisine": "...", "vibe_tags": "cosy,romantic", "description": "...",
      "noise_level": "moderate", "price_band": "mid",
      "is_active": true,
      "slots": [ {"id": 1, "weekday": 4, "start_time": "18:00:00",
                  "end_time": "23:00:00", "max_tables_for_two": 2,
                  "is_quiet_slot": false, "is_active": true}, ... ],
      "blackouts": [ {"start_date": "2026-12-24", "end_date": "2026-12-26"} ],
      "embedding": [ ...384 floats... ],   # optional, for cosine matching
      "source_text": "..."                 # optional, debug
    }
"""
import enum


class PriceBand(str, enum.Enum):
    budget = "budget"
    mid = "mid"
    premium = "premium"
    luxury = "luxury"


class NoiseLevel(str, enum.Enum):
    quiet = "quiet"
    moderate = "moderate"
    lively = "lively"
    loud = "loud"
