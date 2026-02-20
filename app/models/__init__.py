# Import every model here so Alembic autogenerate can discover them
# and so Base.metadata.create_all() works in tests.
# Dependency order matters: referenced tables must come before tables
# that FK-reference them.

from app.models.waitlist import WaitlistSubscriber        # noqa: F401
from app.models.venue_lead import VenueLead               # noqa: F401
from app.models.user import User                          # noqa: F401

# venue must be registered BEFORE anything that FK-references it
from app.models.venue import Venue                        # noqa: F401
from app.models.venue_slot import VenueSlot               # noqa: F401
from app.models.venue_blackout import VenueBlackout       # noqa: F401
from app.models.geocoding_cache import GeocodingCache     # noqa: F401
from app.models.travel_time import TravelTimeCache        # noqa: F401

# Step 7 — embeddings (both FK-reference venue)
from app.models.venue_embedding import VenueEmbedding     # noqa: F401
from app.models.intent_embedding import IntentEmbedding   # noqa: F401
