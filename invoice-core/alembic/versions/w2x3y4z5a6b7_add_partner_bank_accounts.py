"""Add bank_accounts (comma-separated list) to supplier+customer.

Revision ID: w2x3y4z5a6b7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'w2x3y4z5a6b7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('supplier', sa.Column('bank_accounts', sa.Text(), nullable=True))
    op.add_column('customer', sa.Column('bank_accounts', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('customer', 'bank_accounts')
    op.drop_column('supplier', 'bank_accounts')
