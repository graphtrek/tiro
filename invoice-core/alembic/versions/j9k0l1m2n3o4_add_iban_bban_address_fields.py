"""Add iban/bban to supplier+customer, payment_method/payment_due_date to invoice,
and address/exchange/card fields to bank_transaction.

Revision ID: j9k0l1m2n3o4
Revises: 74eb52bf1d12
Create Date: 2026-07-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'j9k0l1m2n3o4'
down_revision: Union[str, Sequence[str], None] = '74eb52bf1d12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('supplier', sa.Column('iban', sa.String(), nullable=True))
    op.add_column('supplier', sa.Column('bban', sa.String(), nullable=True))
    op.drop_column('supplier', 'bank_account')

    op.add_column('customer', sa.Column('iban', sa.String(), nullable=True))
    op.add_column('customer', sa.Column('bban', sa.String(), nullable=True))

    op.add_column('invoice', sa.Column('payment_method', sa.String(), nullable=True))
    op.add_column('invoice', sa.Column('payment_due_date', sa.Date(), nullable=True))

    op.add_column('bank_transaction', sa.Column('counterparty_address', sa.String(), nullable=True))
    op.add_column('bank_transaction', sa.Column('sender_address', sa.String(), nullable=True))
    op.add_column('bank_transaction', sa.Column('counterparty_bank_code', sa.String(), nullable=True))
    op.add_column('bank_transaction', sa.Column('exchange_rate', sa.Float(), nullable=True))
    op.add_column('bank_transaction', sa.Column('exchange_to_currency', sa.String(), nullable=True))
    op.add_column('bank_transaction', sa.Column('card_last_four', sa.String(), nullable=True))
    op.add_column('bank_transaction', sa.Column('note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('bank_transaction', 'note')
    op.drop_column('bank_transaction', 'card_last_four')
    op.drop_column('bank_transaction', 'exchange_to_currency')
    op.drop_column('bank_transaction', 'exchange_rate')
    op.drop_column('bank_transaction', 'counterparty_bank_code')
    op.drop_column('bank_transaction', 'sender_address')
    op.drop_column('bank_transaction', 'counterparty_address')

    op.drop_column('invoice', 'payment_due_date')
    op.drop_column('invoice', 'payment_method')

    op.drop_column('customer', 'bban')
    op.drop_column('customer', 'iban')

    op.add_column('supplier', sa.Column('bank_account', sa.String(), nullable=True))
    op.drop_column('supplier', 'bban')
    op.drop_column('supplier', 'iban')
