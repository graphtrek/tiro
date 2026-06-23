"""Convert invoice ↔ bank_transaction from one-to-many FK to many-to-many junction table.

Revision ID: f5g6h7i8j9k0
Revises: e4f5a6b7c8d9
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f5g6h7i8j9k0'
down_revision: Union[str, Sequence[str], None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'invoice_bank_transaction',
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('bank_transaction_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoice.id']),
        sa.ForeignKeyConstraint(['bank_transaction_id'], ['bank_transaction.id']),
        sa.PrimaryKeyConstraint('invoice_id', 'bank_transaction_id'),
    )
    op.create_index('ix_ibt_bank_transaction_id', 'invoice_bank_transaction', ['bank_transaction_id'])

    op.execute(
        "INSERT INTO invoice_bank_transaction (invoice_id, bank_transaction_id) "
        "SELECT invoice_id, id FROM bank_transaction WHERE invoice_id IS NOT NULL"
    )

    with op.batch_alter_table('bank_transaction') as batch_op:
        batch_op.drop_column('invoice_id')


def downgrade() -> None:
    with op.batch_alter_table('bank_transaction') as batch_op:
        batch_op.add_column(sa.Column('invoice_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_bank_transaction_invoice_id', 'invoice', ['invoice_id'], ['id']
        )

    op.execute(
        "UPDATE bank_transaction "
        "SET invoice_id = ("
        "  SELECT MIN(ibt.invoice_id) FROM invoice_bank_transaction ibt"
        "  WHERE ibt.bank_transaction_id = bank_transaction.id"
        ")"
    )

    op.drop_index('ix_ibt_bank_transaction_id', table_name='invoice_bank_transaction')
    op.drop_table('invoice_bank_transaction')
