"""Replace wise_transaction with bank_transaction; rename sync_log.wise_count to bank_count

Revision ID: e4f5a6b7c8d9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Drop old wise_transaction table ────────────────────────────────────────
    op.drop_index('ix_wise_transaction_wise_transaction_id', table_name='wise_transaction')
    op.drop_index('ix_wise_transaction_invoice_file_id', table_name='wise_transaction')
    op.drop_index('ix_wise_transaction_id', table_name='wise_transaction')
    op.drop_table('wise_transaction')

    # ── Create new bank_transaction table ─────────────────────────────────────
    op.create_table(
        'bank_transaction',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bank', sa.String(), nullable=False),
        sa.Column('transaction_id', sa.String(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), nullable=False),
        sa.Column('direction', sa.String(), nullable=False),
        sa.Column('transaction_date', sa.DateTime(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('payment_reference', sa.String(), nullable=True),
        sa.Column('counterparty_name', sa.String(), nullable=True),
        sa.Column('counterparty_account', sa.String(), nullable=True),
        sa.Column('counterparty_iban', sa.String(), nullable=True),
        sa.Column('transaction_type', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('balance', sa.Float(), nullable=True),
        sa.Column('fees', sa.Float(), nullable=True),
        sa.Column('supplier_id', sa.Integer(), nullable=True),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('invoice_id', sa.Integer(), nullable=True),
        sa.Column('invoice_file_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.ForeignKeyConstraint(['invoice_file_id'], ['invoice_file.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoice.id']),
        sa.ForeignKeyConstraint(['supplier_id'], ['supplier.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bank_transaction_id', 'bank_transaction', ['id'], unique=False)
    op.create_index('ix_bank_transaction_bank', 'bank_transaction', ['bank'], unique=False)
    op.create_index('ix_bank_transaction_transaction_id', 'bank_transaction', ['transaction_id'], unique=True)
    op.create_index('ix_bank_transaction_invoice_file_id', 'bank_transaction', ['invoice_file_id'], unique=False)

    # ── Rename sync_log.wise_count → bank_count ───────────────────────────────
    op.alter_column('sync_log', 'wise_count', new_column_name='bank_count')


def downgrade() -> None:
    # ── Rename sync_log.bank_count → wise_count ───────────────────────────────
    op.alter_column('sync_log', 'bank_count', new_column_name='wise_count')

    # ── Drop bank_transaction table ────────────────────────────────────────────
    op.drop_index('ix_bank_transaction_invoice_file_id', table_name='bank_transaction')
    op.drop_index('ix_bank_transaction_transaction_id', table_name='bank_transaction')
    op.drop_index('ix_bank_transaction_bank', table_name='bank_transaction')
    op.drop_index('ix_bank_transaction_id', table_name='bank_transaction')
    op.drop_table('bank_transaction')

    # ── Recreate wise_transaction table ───────────────────────────────────────
    op.create_table(
        'wise_transaction',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('wise_transaction_id', sa.String(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), nullable=False),
        sa.Column('transaction_date', sa.DateTime(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('payment_reference', sa.String(), nullable=True),
        sa.Column('running_balance', sa.Float(), nullable=True),
        sa.Column('exchange_from', sa.String(), nullable=True),
        sa.Column('exchange_to', sa.String(), nullable=True),
        sa.Column('exchange_rate', sa.Float(), nullable=True),
        sa.Column('payer_name', sa.String(), nullable=True),
        sa.Column('payee_name', sa.String(), nullable=True),
        sa.Column('payee_account_number', sa.String(), nullable=True),
        sa.Column('merchant', sa.String(), nullable=True),
        sa.Column('card_last_four_digits', sa.String(), nullable=True),
        sa.Column('card_holder_full_name', sa.String(), nullable=True),
        sa.Column('attachment', sa.String(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('total_fees', sa.Float(), nullable=True),
        sa.Column('exchange_to_amount', sa.Float(), nullable=True),
        sa.Column('transaction_type', sa.String(), nullable=True),
        sa.Column('transaction_details_type', sa.String(), nullable=True),
        sa.Column('supplier_id', sa.Integer(), nullable=True),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('invoice_id', sa.Integer(), nullable=True),
        sa.Column('invoice_file_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.ForeignKeyConstraint(['invoice_file_id'], ['invoice_file.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoice.id']),
        sa.ForeignKeyConstraint(['supplier_id'], ['supplier.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_wise_transaction_id', 'wise_transaction', ['id'], unique=False)
    op.create_index('ix_wise_transaction_invoice_file_id', 'wise_transaction', ['invoice_file_id'], unique=False)
    op.create_index('ix_wise_transaction_wise_transaction_id', 'wise_transaction', ['wise_transaction_id'], unique=True)
