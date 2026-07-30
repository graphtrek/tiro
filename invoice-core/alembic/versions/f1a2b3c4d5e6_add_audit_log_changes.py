"""add changes column to audit_log

Revision ID: f1a2b3c4d5e6
Revises: d7e8f9a0b1c2
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('audit_log') as batch_op:
        batch_op.add_column(sa.Column('changes', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('audit_log') as batch_op:
        batch_op.drop_column('changes')
