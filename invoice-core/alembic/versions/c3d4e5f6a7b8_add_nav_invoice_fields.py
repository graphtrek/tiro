"""add currency, invoice_operation, invoice_category; rename nav_transaction_id to nav_ins_date

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('invoice', 'nav_transaction_id', new_column_name='nav_ins_date')
    op.add_column('invoice', sa.Column('currency', sa.String(), nullable=True))
    op.add_column('invoice', sa.Column('invoice_operation', sa.String(), nullable=True))
    op.add_column('invoice', sa.Column('invoice_category', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('invoice', 'invoice_category')
    op.drop_column('invoice', 'invoice_operation')
    op.drop_column('invoice', 'currency')
    op.alter_column('invoice', 'nav_ins_date', new_column_name='nav_transaction_id')
