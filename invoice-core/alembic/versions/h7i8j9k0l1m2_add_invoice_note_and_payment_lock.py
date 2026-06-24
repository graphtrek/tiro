"""Add note and payment_status_locked to invoice.

Revision ID: h7i8j9k0l1m2
Revises: g6h7i8j9k0l1
Create Date: 2026-06-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'h7i8j9k0l1m2'
down_revision: Union[str, Sequence[str], None] = 'g6h7i8j9k0l1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('invoice') as batch_op:
        batch_op.add_column(sa.Column('note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('payment_status_locked', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('invoice') as batch_op:
        batch_op.drop_column('payment_status_locked')
        batch_op.drop_column('note')
