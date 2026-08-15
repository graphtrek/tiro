"""add vacation_request table

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-08-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vacation_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_vacation_request_id'), 'vacation_request', ['id'], unique=False)
    op.create_index(op.f('ix_vacation_request_user_id'), 'vacation_request', ['user_id'], unique=False)
    op.create_index(op.f('ix_vacation_request_start_date'), 'vacation_request', ['start_date'], unique=False)
    op.create_index(op.f('ix_vacation_request_end_date'), 'vacation_request', ['end_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_vacation_request_end_date'), table_name='vacation_request')
    op.drop_index(op.f('ix_vacation_request_start_date'), table_name='vacation_request')
    op.drop_index(op.f('ix_vacation_request_user_id'), table_name='vacation_request')
    op.drop_index(op.f('ix_vacation_request_id'), table_name='vacation_request')
    op.drop_table('vacation_request')
