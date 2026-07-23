"""add record column to audit_log

Revision ID: v1w2x3y4z5a6
Revises: u0v1w2x3y4z5
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'v1w2x3y4z5a6'
down_revision: Union[str, Sequence[str], None] = 'u0v1w2x3y4z5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('audit_log') as batch_op:
        batch_op.add_column(sa.Column('record', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('audit_log') as batch_op:
        batch_op.drop_column('record')
