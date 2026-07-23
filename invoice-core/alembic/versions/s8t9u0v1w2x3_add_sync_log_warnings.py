"""Add warning_count and warnings fields to sync_log.

Revision ID: s8t9u0v1w2x3
Revises: r7s8t9u0v1w2
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 's8t9u0v1w2x3'
down_revision: Union[str, Sequence[str], None] = 'r7s8t9u0v1w2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sync_log') as batch_op:
        batch_op.add_column(sa.Column('warning_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('warnings', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sync_log') as batch_op:
        batch_op.drop_column('warnings')
        batch_op.drop_column('warning_count')
