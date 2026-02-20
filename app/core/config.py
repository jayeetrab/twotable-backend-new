from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_ENV: str = "development"

    # Database
    DATABASE_URL: str

    # Auth
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Geocoding
    GEOCODING_PROVIDER: str = "tomtom"
    GEOCODING_API_KEY: str = ""
    GEOCODING_CACHE_TTL_DAYS: int = 30

    # Routing
    ROUTING_PROVIDER: str = "tomtom"
    ROUTING_API_KEY: str = ""
    TRAVEL_TIME_CACHE_TTL_HOURS: int = 72

    # Gemini (text enrichment only)
    GEMINI_API_KEY: str = ""

    # Embeddings
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Add to Settings class
    STRIPE_SECRET_KEY:     str = ""
    STRIPE_WEBHOOK_SECRET: str = ""



settings = Settings()
