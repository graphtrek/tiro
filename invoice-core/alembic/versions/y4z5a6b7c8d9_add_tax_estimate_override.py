"""Add tax_estimate_override table for user-entered monthly revenue overrides.

Revision ID: y4z5a6b7c8d9
Revises: x3y4z5a6b7c8
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'y4z5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'x3y4z5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tax_estimate_override',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('gross_revenue', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('year', 'month', name='uq_tax_estimate_override_year_month'),
    )
    op.create_index(
        op.f('ix_tax_estimate_override_id'), 'tax_estimate_override', ['id'], unique=False
    )
    op.create_index(
        op.f('ix_tax_estimate_override_year'), 'tax_estimate_override', ['year'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_tax_estimate_override_year'), table_name='tax_estimate_override')
    op.drop_index(op.f('ix_tax_estimate_override_id'), table_name='tax_estimate_override')
    op.drop_table('tax_estimate_override')
