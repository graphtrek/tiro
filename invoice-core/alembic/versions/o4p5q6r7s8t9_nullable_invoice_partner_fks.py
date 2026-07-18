"""nullable invoice partner fks

Revision ID: o4p5q6r7s8t9
Revises: n3o4p5q6r7s8
Create Date: 2026-07-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'o4p5q6r7s8t9'
down_revision: Union[str, Sequence[str], None] = 'n3o4p5q6r7s8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sync no longer auto-creates a Supplier/Customer for an unmatched NAV
    # digest — an invoice can now be imported with its partner left unlinked
    # until the user creates it manually, so the FK must allow NULL.
    op.alter_column('invoice', 'supplier_id', existing_type=sa.Integer(), nullable=True)
    op.alter_column('invoice', 'customer_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column('invoice', 'customer_id', existing_type=sa.Integer(), nullable=False)
    op.alter_column('invoice', 'supplier_id', existing_type=sa.Integer(), nullable=False)
