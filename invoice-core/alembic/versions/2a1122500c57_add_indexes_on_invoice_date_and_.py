"""add indexes on invoice_date and transaction_date

Revision ID: 2a1122500c57
Revises: v1w2x3y4z5a6
Create Date: 2026-07-26 02:12:48.382903

"""
from typing import Sequence, Union

from alembic import op

revision: str = '2a1122500c57'
down_revision: Union[str, Sequence[str], None] = 'v1w2x3y4z5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_invoice_invoice_date', 'invoice', ['invoice_date'])
    op.create_index('ix_bank_transaction_transaction_date', 'bank_transaction', ['transaction_date'])


def downgrade() -> None:
    op.drop_index('ix_bank_transaction_transaction_date', table_name='bank_transaction')
    op.drop_index('ix_invoice_invoice_date', table_name='invoice')
