from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.db import mongo
from app.api.v1.auth import router as auth_router
from app.api.v1.profile import router as profile_router
from app.api.v1.venues import router as venues_router
from app.api.v1.suggest import router as suggest_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.discovery import router as discovery_router
from app.api.v1.photos import router as photos_router
from app.api.v1.tonight import router as tonight_router
from app.api.v1.geo import router as geo_router
from app.api.v1.dates import router as dates_router
from app.api.v1.notifications import router as notifications_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo.connect()
    await mongo.ensure_indexes()
    
    from app.core.config import settings
    if settings.APP_ENV == "development":
        db = mongo.get_db()
        print("Development mode: checking dummy profiles...")
        from app.scripts.seed_daters import seed_daters
        await seed_daters(db)
            
    yield
    mongo.close()


app = FastAPI(
    title="TwoTable API",
    version="1.0.0",
    description="Backend for TwoTable — dating meets restaurants (MongoDB).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress JSON responses (feed, venue lists, profiles). Big win over mobile networks.
app.add_middleware(GZipMiddleware, minimum_size=512)

app.include_router(auth_router,     prefix="/api/v1")
app.include_router(profile_router,  prefix="/api/v1")
app.include_router(venues_router,   prefix="/api/v1")
app.include_router(suggest_router,  prefix="/api/v1")
app.include_router(bookings_router, prefix="/api/v1")
app.include_router(discovery_router, prefix="/api/v1")
app.include_router(photos_router, prefix="/api/v1")
app.include_router(tonight_router, prefix="/api/v1")
app.include_router(geo_router, prefix="/api/v1")
app.include_router(dates_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
async def health_check():
    db = mongo.get_db()
    await db.command("ping")
    return {"status": "ok", "version": app.version}
