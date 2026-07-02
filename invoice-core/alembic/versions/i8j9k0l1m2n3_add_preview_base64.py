"""Add preview_base64 to invoice_file.

Revision ID: i8j9k0l1m2n3
Revises: h7i8j9k0l1m2
Create Date: 2026-07-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'i8j9k0l1m2n3'
down_revision: Union[str, Sequence[str], None] = 'h7i8j9k0l1m2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('invoice_file') as batch_op:
        batch_op.add_column(sa.Column('preview_base64', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('invoice_file') as batch_op:
        batch_op.drop_column('preview_base64')
