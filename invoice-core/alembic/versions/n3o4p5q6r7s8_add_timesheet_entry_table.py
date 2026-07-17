"""add timesheet_entry table

Revision ID: n3o4p5q6r7s8
Revises: m2n3o4p5q6r7
Create Date: 2026-07-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'n3o4p5q6r7s8'
down_revision: Union[str, Sequence[str], None] = 'm2n3o4p5q6r7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'timesheet_entry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('activity_type_id', sa.Integer(), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('hours', sa.Float(), nullable=False),
        sa.Column('participants', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['activity_type_id'], ['activity_type.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_timesheet_entry_id'), 'timesheet_entry', ['id'], unique=False)
    op.create_index(op.f('ix_timesheet_entry_user_id'), 'timesheet_entry', ['user_id'], unique=False)
    op.create_index(op.f('ix_timesheet_entry_project_id'), 'timesheet_entry', ['project_id'], unique=False)
    op.create_index(
        op.f('ix_timesheet_entry_activity_type_id'), 'timesheet_entry', ['activity_type_id'], unique=False
    )
    op.create_index(op.f('ix_timesheet_entry_entry_date'), 'timesheet_entry', ['entry_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_timesheet_entry_entry_date'), table_name='timesheet_entry')
    op.drop_index(op.f('ix_timesheet_entry_activity_type_id'), table_name='timesheet_entry')
    op.drop_index(op.f('ix_timesheet_entry_project_id'), table_name='timesheet_entry')
    op.drop_index(op.f('ix_timesheet_entry_user_id'), table_name='timesheet_entry')
    op.drop_index(op.f('ix_timesheet_entry_id'), table_name='timesheet_entry')
    op.drop_table('timesheet_entry')
