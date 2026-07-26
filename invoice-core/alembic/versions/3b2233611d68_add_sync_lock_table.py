"""add sync_lock table (DEF-012 concurrency guard)

Revision ID: 3b2233611d68
Revises: 2a1122500c57
Create Date: 2026-07-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '3b2233611d68'
down_revision: Union[str, Sequence[str], None] = '2a1122500c57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sync_lock',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('locked_by', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('sync_lock')
