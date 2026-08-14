"""Add fizetes_kalkulator_state table for persisting the wage/dividend calculator inputs.

Revision ID: z5a6b7c8d9e0
Revises: y4z5a6b7c8d9
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'z5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = 'y4z5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fizetes_kalkulator_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('net_wage', sa.Float(), nullable=False),
        sa.Column('revenue', sa.Float(), nullable=False),
        sa.Column('revenue_touched', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_fizetes_kalkulator_state_id'), 'fizetes_kalkulator_state', ['id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_fizetes_kalkulator_state_id'), table_name='fizetes_kalkulator_state')
    op.drop_table('fizetes_kalkulator_state')
