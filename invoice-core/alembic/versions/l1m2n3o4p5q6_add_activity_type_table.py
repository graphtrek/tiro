"""add activity_type table (admin master data for the future timesheet feature)

Revision ID: l1m2n3o4p5q6
Revises: k0l1m2n3o4p5
Create Date: 2026-07-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'l1m2n3o4p5q6'
down_revision: Union[str, Sequence[str], None] = 'k0l1m2n3o4p5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'activity_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_activity_type_id'), 'activity_type', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_activity_type_id'), table_name='activity_type')
    op.drop_table('activity_type')
