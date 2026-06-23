"""Add manual link lock fields to invoice, bank_transaction, and invoice_bank_transaction.

Revision ID: g6h7i8j9k0l1
Revises: f5g6h7i8j9k0
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'g6h7i8j9k0l1'
down_revision: Union[str, Sequence[str], None] = 'f5g6h7i8j9k0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('invoice') as batch_op:
        batch_op.add_column(sa.Column('invoice_file_locked', sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table('bank_transaction') as batch_op:
        batch_op.add_column(sa.Column('invoice_file_locked', sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table('invoice_bank_transaction') as batch_op:
        batch_op.add_column(sa.Column('manual', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('invoice_bank_transaction') as batch_op:
        batch_op.drop_column('manual')

    with op.batch_alter_table('bank_transaction') as batch_op:
        batch_op.drop_column('invoice_file_locked')

    with op.batch_alter_table('invoice') as batch_op:
        batch_op.drop_column('invoice_file_locked')
