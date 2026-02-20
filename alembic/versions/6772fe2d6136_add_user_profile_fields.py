"""add user profile fields

Revision ID: 6772fe2d6136
Revises: 222c449559cd
Create Date: 2026-02-20 05:54:19.934262

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '6772fe2d6136'
down_revision: Union[str, None] = '222c449559cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('preferred_mood',        sa.String(60),  nullable=True))
    op.add_column('users', sa.Column('preferred_budget',      sa.String(20),  nullable=True))
    op.add_column('users', sa.Column('preferred_stage',       sa.String(60),  nullable=True))
    op.add_column('users', sa.Column('dietary_requirements',  sa.String(255), nullable=True))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True,
                                     server_default=sa.text('now()')))


def downgrade() -> None:
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'dietary_requirements')
    op.drop_column('users', 'preferred_stage')
    op.drop_column('users', 'preferred_budget')
    op.drop_column('users', 'preferred_mood')
