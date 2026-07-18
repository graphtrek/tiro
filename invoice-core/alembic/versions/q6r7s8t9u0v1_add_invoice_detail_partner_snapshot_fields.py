"""add invoice_detail partner snapshot fields

Revision ID: q6r7s8t9u0v1
Revises: p5q6r7s8t9u0
Create Date: 2026-07-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'q6r7s8t9u0v1'
down_revision: Union[str, Sequence[str], None] = 'p5q6r7s8t9u0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoice_detail', sa.Column('supplier_name', sa.String(), nullable=True))
    op.add_column('invoice_detail', sa.Column('supplier_tax_number', sa.String(), nullable=True))
    op.add_column('invoice_detail', sa.Column('supplier_address', sa.String(), nullable=True))
    op.add_column('invoice_detail', sa.Column('supplier_bank_account', sa.String(), nullable=True))
    op.add_column('invoice_detail', sa.Column('customer_name', sa.String(), nullable=True))
    op.add_column('invoice_detail', sa.Column('customer_tax_number', sa.String(), nullable=True))
    op.add_column('invoice_detail', sa.Column('customer_address', sa.String(), nullable=True))
    op.add_column('invoice_detail', sa.Column('customer_bank_account', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('invoice_detail', 'customer_bank_account')
    op.drop_column('invoice_detail', 'customer_address')
    op.drop_column('invoice_detail', 'customer_tax_number')
    op.drop_column('invoice_detail', 'customer_name')
    op.drop_column('invoice_detail', 'supplier_bank_account')
    op.drop_column('invoice_detail', 'supplier_address')
    op.drop_column('invoice_detail', 'supplier_tax_number')
    op.drop_column('invoice_detail', 'supplier_name')
