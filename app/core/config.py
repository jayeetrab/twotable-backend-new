from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_ENV: str = "development"
    # Public base URL used to build absolute photo URLs returned to the app.
    PUBLIC_BASE_URL: str = "http://localhost:8009"

    # Database — MongoDB
    MONGODB_URI: str
    MONGODB_DB: str = "TwoTable"
    # Raw Google-Places venue collection used by the seeding script
    MONGODB_RAW_VENUES_COLLECTION: str = "venues_bristol_new"

    # Auth
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # Dev phone-OTP: the code accepted for every number until real SMS (Twilio) is wired.
    DEV_OTP_CODE: str = "12345"

    # Embeddings (local sentence-transformers, in-app cosine).
    # bge-small-en-v1.5 is a much stronger 384-dim model than MiniLM (top MTEB for its size),
    # still CPU-friendly, offline, and no API key. Dim stays 384 so stored vectors are
    # format-compatible (venues must be re-embedded once after switching — see scripts).
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384

    # Mapbox — geocoding (forward/reverse) + real travel times. Set MAPBOX_TOKEN in .env.
    MAPBOX_TOKEN: str = ""

    # Redis — TTL cache for venue lists / suggestions. Cache degrades gracefully if down.
    REDIS_URL: str = "redis://localhost:6379/0"

    # Gemini — optional, used only for venue text enrichment while seeding
    GEMINI_API_KEY: str = ""

    # Stripe — optional. When unset, bookings auto-confirm (dev mode).
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""

    # Spotify (optional social connect)
    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""
    SPOTIFY_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/auth/spotify/callback"
    FRONTEND_REDIRECT_URL: str = "http://127.0.0.1:3000/profile/connected"


settings = Settings()
