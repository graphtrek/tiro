"""add project table + project_permitted_user join table

Revision ID: m2n3o4p5q6r7
Revises: l1m2n3o4p5q6
Create Date: 2026-07-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'm2n3o4p5q6r7'
down_revision: Union[str, Sequence[str], None] = 'l1m2n3o4p5q6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'project',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('sequence_no', sa.Integer(), nullable=False),
        sa.Column('short_name', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.UniqueConstraint('customer_id', 'sequence_no', name='uq_project_customer_seq'),
    )
    op.create_index(op.f('ix_project_id'), 'project', ['id'], unique=False)
    op.create_index(op.f('ix_project_customer_id'), 'project', ['customer_id'], unique=False)
    op.create_index(op.f('ix_project_code'), 'project', ['code'], unique=False)

    op.create_table(
        'project_permitted_user',
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('project_id', 'user_id'),
    )


def downgrade() -> None:
    op.drop_table('project_permitted_user')
    op.drop_index(op.f('ix_project_code'), table_name='project')
    op.drop_index(op.f('ix_project_customer_id'), table_name='project')
    op.drop_index(op.f('ix_project_id'), table_name='project')
    op.drop_table('project')
