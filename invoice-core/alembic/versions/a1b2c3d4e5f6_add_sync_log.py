"""add sync_log table

Revision ID: a1b2c3d4e5f6
Revises: d7bc3a3f91d1
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd7bc3a3f91d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sync_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('mode', sa.String(), nullable=True),
        sa.Column('invoice_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('wise_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('errors', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sync_log_id'), 'sync_log', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_sync_log_id'), table_name='sync_log')
    op.drop_table('sync_log')
