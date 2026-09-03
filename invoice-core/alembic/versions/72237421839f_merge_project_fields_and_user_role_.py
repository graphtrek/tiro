"""merge project fields and user role branches

Revision ID: 72237421839f
Revises: b7c8d9e0f1a2, d3e4f5a6b7c8
Create Date: 2026-09-03 22:24:12.682199

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72237421839f'
down_revision: Union[str, Sequence[str], None] = ('b7c8d9e0f1a2', 'd3e4f5a6b7c8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
