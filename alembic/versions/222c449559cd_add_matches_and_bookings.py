"""add matches and bookings

Revision ID: 222c449559cd
Revises: <your_previous_revision_id>
Create Date: 2026-02-20

"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '222c449559cd'
down_revision: Union[str, None] = '141ab29ffc1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # enums already exist in DB — just ensure they're there
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE matchstatus AS ENUM ('pending', 'confirmed', 'cancelled', 'completed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE bookingstatus AS ENUM ('pending', 'confirmed', 'cancelled', 'refunded');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # matches — use Text for status to avoid SQLAlchemy auto-creating enum
    op.execute("""
        CREATE TABLE matches (
            id         SERIAL PRIMARY KEY,
            user_a_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            user_b_id  INTEGER          REFERENCES users(id) ON DELETE CASCADE,
            venue_id   INTEGER          REFERENCES venues(id) ON DELETE SET NULL,
            slot_id    INTEGER          REFERENCES venue_slots(id) ON DELETE SET NULL,
            status     matchstatus NOT NULL DEFAULT 'pending',
            city       VARCHAR(120) NOT NULL,
            date       VARCHAR(20)  NOT NULL,
            time       VARCHAR(10)  NOT NULL,
            mood       VARCHAR(60),
            stage      VARCHAR(60),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_matches_user_a_id ON matches (user_a_id)")
    op.execute("CREATE INDEX ix_matches_user_b_id ON matches (user_b_id)")
    op.execute("CREATE INDEX ix_matches_status    ON matches (status)")

    # bookings
    op.execute("""
        CREATE TABLE bookings (
            id                       SERIAL PRIMARY KEY,
            match_id                 INTEGER NOT NULL REFERENCES matches(id)     ON DELETE CASCADE,
            venue_id                 INTEGER          REFERENCES venues(id)      ON DELETE SET NULL,
            slot_id                  INTEGER          REFERENCES venue_slots(id) ON DELETE SET NULL,
            status                   bookingstatus NOT NULL DEFAULT 'pending',
            stripe_payment_intent_id VARCHAR(200),
            deposit_amount_pence     INTEGER NOT NULL DEFAULT 1000,
            booked_date              VARCHAR(20)  NOT NULL,
            booked_time              VARCHAR(10)  NOT NULL,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_bookings_match_id    ON bookings (match_id)")
    op.execute("CREATE INDEX ix_bookings_slot_id     ON bookings (slot_id)")
    op.execute("CREATE INDEX ix_bookings_status      ON bookings (status)")
    op.execute("CREATE INDEX ix_bookings_booked_date ON bookings (booked_date)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bookings")
    op.execute("DROP TABLE IF EXISTS matches")
    op.execute("DROP TYPE IF EXISTS bookingstatus")
    op.execute("DROP TYPE IF EXISTS matchstatus")
