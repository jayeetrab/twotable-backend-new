

"""add venue_embeddings and intent_embeddings

Revision ID: 52f6c2720b9c
Revises: b7cf1f5d39df
Branch Labels: None
Depends on: None

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector   # ← the missing import


# revision identifiers, used by Alembic.
revision = '52f6c2720b9c'
down_revision = 'b7cf1f5d39df' 
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE venue_embeddings "
        "ALTER COLUMN embedding TYPE vector(384)"
    )
    op.execute(
        "ALTER TABLE intent_embeddings "
        "ALTER COLUMN embedding TYPE vector(384)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE venue_embeddings "
        "ALTER COLUMN embedding TYPE vector(768)"
    )
    op.execute(
        "ALTER TABLE intent_embeddings "
        "ALTER COLUMN embedding TYPE vector(768)"
    )