"""Add known_names (comma-separated list) to supplier+customer.

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'x3y4z5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'w2x3y4z5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('supplier', sa.Column('known_names', sa.Text(), nullable=True))
    op.add_column('customer', sa.Column('known_names', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('customer', 'known_names')
    op.drop_column('supplier', 'known_names')
