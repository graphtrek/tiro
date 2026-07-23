"""Add supplier_locked and customer_locked fields to invoice and bank_transaction.

Revision ID: r7s8t9u0v1w2
Revises: q6r7s8t9u0v1
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'r7s8t9u0v1w2'
down_revision: Union[str, Sequence[str], None] = 'q6r7s8t9u0v1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('invoice') as batch_op:
        batch_op.add_column(sa.Column('supplier_locked', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('customer_locked', sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table('bank_transaction') as batch_op:
        batch_op.add_column(sa.Column('supplier_locked', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('customer_locked', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('bank_transaction') as batch_op:
        batch_op.drop_column('customer_locked')
        batch_op.drop_column('supplier_locked')

    with op.batch_alter_table('invoice') as batch_op:
        batch_op.drop_column('customer_locked')
        batch_op.drop_column('supplier_locked')
