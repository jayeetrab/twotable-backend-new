import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import asyncio
from datetime import time

from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import select

import app.models.user              # noqa: F401
import app.models.waitlist          # noqa: F401
import app.models.venue_lead        # noqa: F401
import app.models.geocoding_cache   # noqa: F401
import app.models.venue             # noqa: F401
import app.models.venue_slot        # noqa: F401
import app.models.venue_blackout    # noqa: F401

from app.db.session import async_session_factory
from app.models.venue import Venue, PriceBand
from app.models.venue_slot import VenueSlot
from app.services.gemini_enrich import enrich_venue_with_gemini

# ── Config ────────────────────────────────────────────────────────────────────


MONGO_URI = "mongodb+srv://twotable:JY353i60x89p8SMb@twotablecluster.jjmnbl8.mongodb.net/?appName=TwoTableCluster"
MONGO_DB = "TwoTable"
MONGO_COLLECTION = "venues_bristol_new"  

PRICE_MAP = {
    "PRICE_LEVEL_FREE": PriceBand.budget,
    "PRICE_LEVEL_INEXPENSIVE": PriceBand.budget,
    "PRICE_LEVEL_MODERATE": PriceBand.mid,
    "PRICE_LEVEL_EXPENSIVE": PriceBand.premium,
    "PRICE_LEVEL_VERY_EXPENSIVE": PriceBand.luxury,
}

DINING_TYPES = {
    "restaurant", "bar", "cafe", "bakery", "meal_takeaway",
    "meal_delivery", "food", "night_club", "wine_bar",
    "turkish_restaurant", "italian_restaurant", "indian_restaurant",
    "chinese_restaurant", "japanese_restaurant", "seafood_restaurant",
    "steak_house", "fast_food_restaurant", "coffee_shop",
    "mediterranean_restaurant", "french_restaurant", "pizza_restaurant",
    "american_restaurant", "greek_restaurant", "mexican_restaurant",
    "thai_restaurant", "vietnamese_restaurant", "spanish_restaurant",
    "middle_eastern_restaurant", "lebanese_restaurant", "pub",
    "gastropub", "sushi_restaurant", "ramen_restaurant",
    "brunch_restaurant", "dessert_restaurant", "ice_cream_shop",
    "sandwich_shop", "breakfast_restaurant",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def google_day_to_iso(google_day: int) -> int:
    return (google_day - 1) % 7


def parse_slots(periods: list) -> list[dict]:
    slots = []
    for period in periods:
        o = period.get("open", {})
        c = period.get("close", {})
        if not o or not c:
            continue
        slots.append({
            "weekday": google_day_to_iso(o["day"]),
            "start_time": time(o["hour"], o.get("minute", 0)),
            "end_time": time(c["hour"], c.get("minute", 0)),
            "max_tables_for_two": 2,
            "is_quiet_slot": False,
        })
    return slots


def extract_postcode(address_components: list) -> str | None:
    for comp in address_components:
        if "postal_code" in comp.get("types", []):
            return comp.get("longText") or comp.get("shortText")
    return None


def extract_reviews(raw_reviews: list) -> list[str]:
    texts = []
    for r in raw_reviews:
        if isinstance(r, str):
            texts.append(r)
        elif isinstance(r, dict):
            text_field = r.get("text", {})
            if isinstance(text_field, str):
                texts.append(text_field)
            elif isinstance(text_field, dict):
                val = text_field.get("text", "")
                if val:
                    texts.append(val)
    return [t for t in texts if t][:5]


# ── Per-venue import — owns its own session ───────────────────────────────────

async def import_venue(doc: dict) -> str:
    """
    Returns: 'imported', 'skipped', or 'failed'
    Each call gets its own DB session — isolates failures completely.
    """
    core = doc.get("core", {})
    types = core.get("types", [])
    name = core.get("name", "Unknown")

    # Skip non-dining
    if not any(t in DINING_TYPES for t in types):
        return "skipped"

    async with async_session_factory() as db:
        try:
            # Check duplicate
            existing = await db.execute(
                select(Venue).where(Venue.name == name)
            )
            if existing.scalar_one_or_none():
                print(f"  ⏭  Already exists: {name}")
                return "skipped"

            location = doc.get("location", {})
            rating = doc.get("rating", {})
            hours = doc.get("hours", {}).get("regular_opening_hours", {})
            attributes = doc.get("attributes", {})

            # Gemini enrichment
            try:
                enriched = await enrich_venue_with_gemini(
                    name=name,
                    types_list=types,
                    reviews=extract_reviews(doc.get("reviews", [])),
                    attributes=attributes,
                )
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    print(f"  ⏸  Rate limited — fallback: {name}")
                else:
                    print(f"  ⚠️  Gemini error ({name}): {err}")
                enriched = {
                    "noise_level": "moderate",
                    "vibe_tags": "date night, restaurant",
                    "description": f"{name} is a restaurant in Bristol.",
                }

            # Price level
            price_level = (
                rating.get("price_level")
                or doc.get("google_raw", {}).get("priceLevel")
            )

            venue = Venue(
                name=name,
                email=None,          # Google doesn't provide email
                phone=doc.get("contact", {}).get("international_phone_number"),
                website=core.get("website_uri"),
                address=location.get("formatted_address", ""),
                city=doc.get("city", "Bristol"),
                country="UK",
                postcode=doc.get("postcode") or extract_postcode(
                    location.get("address_components", [])
                ),
                lat=location.get("lat"),
                lng=location.get("lng"),
                cuisine=core.get("primary_type_display_name", {}).get("text"),
                price_band=PRICE_MAP.get(price_level),
                noise_level=enriched.get("noise_level"),
                vibe_tags=enriched.get("vibe_tags"),
                description=enriched.get("description"),
                is_active=True,
            )
            db.add(venue)
            await db.flush()

            periods = hours.get("periods", [])
            slot_list = parse_slots(periods)
            for slot_data in slot_list:
                db.add(VenueSlot(venue_id=venue.id, **slot_data))

            await db.commit()
            print(f"  ✅ {name} | {venue.city} | {price_level} | {len(slot_list)} slots")
            return "imported"

        except Exception as e:
            await db.rollback()
            print(f"  ❌ Failed {name}: {e}")
            return "failed"


# ── Main runner ───────────────────────────────────────────────────────────────

async def run():
    mongo = AsyncIOMotorClient(MONGO_URI)
    dbs = await mongo.list_database_names()
    print(f"✅ MongoDB connected. Databases: {dbs}")

    collection = mongo[MONGO_DB][MONGO_COLLECTION]
    total = await collection.count_documents({"city": "Bristol"})
    print(f"📦 Found {total} Bristol docs in '{MONGO_DB}.{MONGO_COLLECTION}'")

    if total == 0:
        sample = await collection.find_one({})
        if sample:
            print(f"   Sample keys: {list(sample.keys())}")
            print(f"   Sample city: {sample.get('city')!r}")
        return

    # ── Fetch ALL docs into memory first ──────────────────────────────────────
    # Avoids cursor timeout caused by long asyncio.sleep() between venues
    print("📥 Loading all docs into memory...")
    docs = await collection.find({"city": "Bristol"}).to_list(length=None)
    print(f"📥 Loaded {len(docs)} docs. Starting import...\n")
    mongo.close()  # done with Mongo now

    imported = skipped = failed = 0

    for doc in docs:
        result = await import_venue(doc)
        if result == "imported":
            imported += 1
            await asyncio.sleep(4)   # Gemini rate limit buffer
        elif result == "skipped":
            skipped += 1
        else:
            failed += 1

    print(f"\n{'='*50}")
    print(f"✅ Imported:  {imported}")
    print(f"⏭  Skipped:   {skipped}")
    print(f"❌ Failed:    {failed}")
    print(f"{'='*50}")

if __name__ == "__main__":
    asyncio.run(run())
