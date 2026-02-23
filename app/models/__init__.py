from app.models.waitlist import WaitlistSubscriber            # noqa: F401
from app.models.venue_lead import VenueLead                   # noqa: F401
from app.models.user import User                              # noqa: F401

# Step 1
from app.models.user_profile import UserProfile               # noqa: F401
from app.models.user_availability import UserAvailability     # noqa: F401

# Step 2
from app.models.user_social_connection import UserSocialConnection  # noqa: F401
from app.models.user_social_signal import UserSocialSignal          # noqa: F401

# venues must be registered BEFORE anything that FK-references them
from app.models.venue import Venue                            # noqa: F401
from app.models.venue_slot import VenueSlot                   # noqa: F401
from app.models.venue_blackout import VenueBlackout           # noqa: F401
from app.models.geocoding_cache import GeocodingCache         # noqa: F401
from app.models.travel_time import TravelTimeCache            # noqa: F401
from app.models.venue_embedding import VenueEmbedding         # noqa: F401
from app.models.intent_embedding import IntentEmbedding       # noqa: F401
