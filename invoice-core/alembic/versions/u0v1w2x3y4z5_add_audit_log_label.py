"""add label column to audit_log

Revision ID: u0v1w2x3y4z5
Revises: t9u0v1w2x3y4
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'u0v1w2x3y4z5'
down_revision: Union[str, Sequence[str], None] = 't9u0v1w2x3y4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('audit_log') as batch_op:
        batch_op.add_column(sa.Column('label', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('audit_log') as batch_op:
        batch_op.drop_column('label')
