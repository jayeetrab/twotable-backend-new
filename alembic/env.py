import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
import app.models.venue_lead
from alembic import context
import app.models.user   
import app.models.geocoding_cache  # noqa: F401  ← ADD
import app.models.travel_time
from app.core.config import settings
from app.db.session import Base

# ── Order matters: dependencies first ─────────────────────────────────────────
import app.models.waitlist          # noqa: F401
import app.models.venue_lead        # noqa: F401
import app.models.geocoding_cache   # noqa: F401

# venues must be registered BEFORE anything that FK-references it
import app.models.venue             # noqa: F401
import app.models.venue_slot        # noqa: F401
import app.models.venue_blackout    # noqa: F401
import app.models.travel_time       # noqa: F401  ← safe now


# ── Alembic config object — MUST come before anything that uses `config` ──
config = context.config

# Logging setup from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", str(settings.DATABASE_URL))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(
        str(settings.DATABASE_URL),
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
