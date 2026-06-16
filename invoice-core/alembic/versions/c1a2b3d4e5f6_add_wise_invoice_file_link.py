"""add wise_transaction.invoice_file_id link

Revision ID: c1a2b3d4e5f6
Revises: b88ba50b0563
Create Date: 2026-06-16 22:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b88ba50b0563'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('wise_transaction', sa.Column('invoice_file_id', sa.Integer(), nullable=True))
    op.create_index(
        op.f('ix_wise_transaction_invoice_file_id'),
        'wise_transaction',
        ['invoice_file_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_wise_transaction_invoice_file_id',
        'wise_transaction',
        'invoice_file',
        ['invoice_file_id'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_wise_transaction_invoice_file_id', 'wise_transaction', type_='foreignkey')
    op.drop_index(op.f('ix_wise_transaction_invoice_file_id'), table_name='wise_transaction')
    op.drop_column('wise_transaction', 'invoice_file_id')
