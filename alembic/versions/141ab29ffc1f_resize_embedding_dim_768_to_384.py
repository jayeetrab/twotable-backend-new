"""resize embedding dim 768 to 384

Revision ID: 141ab29ffc1f
Revises: 52f6c2720b9c
Create Date: 2026-02-19 14:49:47.162354

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '141ab29ffc1f'
down_revision: Union[str, None] = '52f6c2720b9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
