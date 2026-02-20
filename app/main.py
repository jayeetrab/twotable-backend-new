from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.db.session import engine
from app.api.v1.waitlist import router as waitlist_router
from app.api.v1.venues import router as venues_router
from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.suggest import router as suggest_router
from app.api.v1.bookings import router as bookings_router
# ← embeddings router REMOVED — all embed routes now live in admin.py


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    yield


app = FastAPI(
    title="TwoTable API",
    version="0.8.0",
    description="Backend for TwoTable – dating meets restaurants.",
    lifespan=lifespan,
)

app.include_router(bookings_router, prefix="/api/v1")
app.include_router(waitlist_router,  prefix="/api/v1")
app.include_router(venues_router,    prefix="/api/v1")
app.include_router(auth_router,      prefix="/api/v1")
app.include_router(admin_router,     prefix="/api/v1")
app.include_router(suggest_router,   prefix="/api/v1")


@app.get("/health", tags=["meta"])
async def health_check():
    return {"status": "ok", "version": app.version}

