"""add start_date and project_type to project

Revision ID: 08b84edf4494
Revises: 3b2233611d68
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '08b84edf4494'
down_revision: Union[str, Sequence[str], None] = '3b2233611d68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('project') as batch_op:
        batch_op.add_column(
            sa.Column('start_date', sa.Date(), nullable=False, server_default=sa.text('CURRENT_DATE'))
        )
        batch_op.add_column(
            sa.Column(
                'project_type',
                sa.Enum('OTLET', 'SZAMLAZHATO', 'PRESALES', name='_projecttype', native_enum=False),
                nullable=False,
                server_default='SZAMLAZHATO',
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('project') as batch_op:
        batch_op.drop_column('project_type')
        batch_op.drop_column('start_date')
