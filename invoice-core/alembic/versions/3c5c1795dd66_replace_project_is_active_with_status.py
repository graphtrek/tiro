"""replace project.is_active with status (OPEN/CLOSED/ONHOLD)

Revision ID: 3c5c1795dd66
Revises: 08b84edf4494
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '3c5c1795dd66'
down_revision: Union[str, Sequence[str], None] = '08b84edf4494'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('project') as batch_op:
        batch_op.add_column(
            sa.Column(
                'status',
                sa.Enum('OPEN', 'CLOSED', 'ONHOLD', name='_projectstatus', native_enum=False),
                nullable=False,
                server_default='OPEN',
            )
        )
    op.execute("UPDATE project SET status = 'CLOSED' WHERE is_active = FALSE")
    with op.batch_alter_table('project') as batch_op:
        batch_op.drop_column('is_active')


def downgrade() -> None:
    with op.batch_alter_table('project') as batch_op:
        batch_op.add_column(
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true())
        )
    op.execute("UPDATE project SET is_active = FALSE WHERE status = 'CLOSED'")
    with op.batch_alter_table('project') as batch_op:
        batch_op.drop_column('status')
