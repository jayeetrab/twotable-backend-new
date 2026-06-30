"""
Seed the `venues` collection from the raw Google-Places collection on Atlas.

Reads MONGODB_RAW_VENUES_COLLECTION (default `venues_bristol_new`), flattens
each dining venue into the document shape the API expects (see app.models.venue),
embeds slots + an optional similarity vector, and upserts into `venues`.

Usage:
    python -m app.scripts.seed_venues                 # flatten + embed
    python -m app.scripts.seed_venues --no-embed      # skip vectors (fast)
    python -m app.scripts.seed_venues --city Bristol  # filter city
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import settings
from app.db import mongo
from app.services import embeddings

PRICE_MAP = {
    "PRICE_LEVEL_FREE": "budget",
    "PRICE_LEVEL_INEXPENSIVE": "budget",
    "PRICE_LEVEL_MODERATE": "mid",
    "PRICE_LEVEL_EXPENSIVE": "premium",
    "PRICE_LEVEL_VERY_EXPENSIVE": "luxury",
}

DINING_TYPES = {
    "restaurant", "bar", "cafe", "bakery", "meal_takeaway", "meal_delivery",
    "food", "night_club", "wine_bar", "turkish_restaurant", "italian_restaurant",
    "indian_restaurant", "chinese_restaurant", "japanese_restaurant",
    "seafood_restaurant", "steak_house", "fast_food_restaurant", "coffee_shop",
    "mediterranean_restaurant", "french_restaurant", "pizza_restaurant",
    "american_restaurant", "greek_restaurant", "mexican_restaurant",
    "thai_restaurant", "vietnamese_restaurant", "spanish_restaurant",
    "middle_eastern_restaurant", "lebanese_restaurant", "pub", "gastropub",
    "sushi_restaurant", "ramen_restaurant", "brunch_restaurant",
    "dessert_restaurant", "ice_cream_shop", "sandwich_shop", "breakfast_restaurant",
}


def _google_day_to_iso(google_day: int) -> int:
    return (google_day - 1) % 7  # 0=Monday … 6=Sunday


def _hhmmss(hour: int, minute: int = 0) -> str:
    return f"{hour:02d}:{minute:02d}:00"


def _parse_slots(periods: list, next_id_fn) -> list:
    slots = []
    for period in periods:
        o, c = period.get("open", {}), period.get("close", {})
        if not o or not c:
            continue
        slots.append({
            "weekday": _google_day_to_iso(o["day"]),
            "start_time": _hhmmss(o["hour"], o.get("minute", 0)),
            "end_time": _hhmmss(c["hour"], c.get("minute", 0)),
            "max_tables_for_two": 2,
            "is_quiet_slot": False,
            "is_active": True,
        })
    return slots


def _extract_postcode(components: list):
    for comp in components:
        if "postal_code" in comp.get("types", []):
            return comp.get("longText") or comp.get("shortText")
    return None


def _flatten(doc: dict) -> dict | None:
    core = doc.get("core", {})
    types = core.get("types", [])
    if not any(t in DINING_TYPES for t in types):
        return None

    location = doc.get("location", {})
    rating = doc.get("rating", {})
    hours = doc.get("hours", {}).get("regular_opening_hours", {})
    price_level = rating.get("price_level") or doc.get("google_raw", {}).get("priceLevel")

    return {
        "name": core.get("name", "Unknown"),
        "email": None,
        "phone": doc.get("contact", {}).get("international_phone_number"),
        "website": core.get("website_uri"),
        "address": location.get("formatted_address", ""),
        "city": doc.get("city", "Bristol"),
        "country": "UK",
        "postcode": doc.get("postcode") or _extract_postcode(location.get("address_components", [])),
        "lat": location.get("lat"),
        "lng": location.get("lng"),
        "cuisine": (core.get("primary_type_display_name") or {}).get("text"),
        "price_band": PRICE_MAP.get(price_level),
        "noise_level": "moderate",
        "vibe_tags": "date night, restaurant",
        "description": f"{core.get('name', 'This venue')} is a restaurant in {doc.get('city', 'Bristol')}.",
        "is_active": True,
        "_periods": hours.get("periods", []),
    }


async def run(city: str | None, do_embed: bool) -> None:
    mongo.connect()
    db = mongo.get_db()
    raw = db[settings.MONGODB_RAW_VENUES_COLLECTION]

    query = {"city": city} if city else {}
    docs = await raw.find(query).to_list(length=None)
    print(f"📦 Loaded {len(docs)} raw docs from '{settings.MONGODB_RAW_VENUES_COLLECTION}'")

    imported = skipped = 0
    for doc in docs:
        flat = _flatten(doc)
        if flat is None:
            skipped += 1
            continue

        existing = await db[mongo.VENUES].find_one({"name": flat["name"], "city": flat["city"]})
        if existing:
            skipped += 1
            continue

        periods = flat.pop("_periods")
        slots = _parse_slots(periods, None)
        for s in slots:
            s["id"] = await mongo.next_id("venue_slots")
        flat["slots"] = slots
        flat["blackouts"] = []

        if do_embed:
            flat["source_text"] = embeddings.build_venue_source_text(flat)
            flat["embedding"] = await embeddings.embed(flat["source_text"])

        flat["_id"] = await mongo.next_id("venues")
        await db[mongo.VENUES].insert_one(flat)
        imported += 1
        print(f"  ✅ {flat['name']} | {flat['city']} | {len(slots)} slots")

    print(f"\n{'='*50}\n✅ Imported: {imported}\n⏭  Skipped: {skipped}\n{'='*50}")
    mongo.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default=None, help="Filter raw docs by city")
    parser.add_argument("--no-embed", action="store_true", help="Skip similarity vectors")
    args = parser.parse_args()
    asyncio.run(run(city=args.city, do_embed=not args.no_embed))
    sys.exit(0)
