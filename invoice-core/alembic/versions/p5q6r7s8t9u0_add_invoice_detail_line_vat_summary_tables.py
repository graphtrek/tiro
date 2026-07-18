"""add invoice_detail, invoice_line, invoice_vat_summary tables

Revision ID: p5q6r7s8t9u0
Revises: o4p5q6r7s8t9
Create Date: 2026-07-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'p5q6r7s8t9u0'
down_revision: Union[str, Sequence[str], None] = 'o4p5q6r7s8t9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'invoice_detail',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('raw_xml', sa.Text(), nullable=True),
        sa.Column('invoice_category', sa.String(), nullable=True),
        sa.Column('delivery_date', sa.Date(), nullable=True),
        sa.Column('currency_code', sa.String(), nullable=True),
        sa.Column('exchange_rate', sa.Float(), nullable=True),
        sa.Column('invoice_appearance', sa.String(), nullable=True),
        sa.Column('invoice_net_amount', sa.Float(), nullable=True),
        sa.Column('invoice_vat_amount', sa.Float(), nullable=True),
        sa.Column('invoice_gross_amount', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoice.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('invoice_id'),
    )
    op.create_index(op.f('ix_invoice_detail_id'), 'invoice_detail', ['id'], unique=False)
    op.create_index(op.f('ix_invoice_detail_invoice_id'), 'invoice_detail', ['invoice_id'], unique=False)

    op.create_table(
        'invoice_line',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('line_number', sa.String(), nullable=True),
        sa.Column('line_description', sa.Text(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('unit_of_measure', sa.String(), nullable=True),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.Column('line_net_amount', sa.Float(), nullable=True),
        sa.Column('line_vat_rate', sa.Float(), nullable=True),
        sa.Column('line_vat_amount', sa.Float(), nullable=True),
        sa.Column('line_gross_amount', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoice.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invoice_line_id'), 'invoice_line', ['id'], unique=False)
    op.create_index(op.f('ix_invoice_line_invoice_id'), 'invoice_line', ['invoice_id'], unique=False)

    op.create_table(
        'invoice_vat_summary',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('vat_rate', sa.Float(), nullable=True),
        sa.Column('vat_rate_net_amount', sa.Float(), nullable=True),
        sa.Column('vat_rate_vat_amount', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoice.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invoice_vat_summary_id'), 'invoice_vat_summary', ['id'], unique=False)
    op.create_index(op.f('ix_invoice_vat_summary_invoice_id'), 'invoice_vat_summary', ['invoice_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_invoice_vat_summary_invoice_id'), table_name='invoice_vat_summary')
    op.drop_index(op.f('ix_invoice_vat_summary_id'), table_name='invoice_vat_summary')
    op.drop_table('invoice_vat_summary')

    op.drop_index(op.f('ix_invoice_line_invoice_id'), table_name='invoice_line')
    op.drop_index(op.f('ix_invoice_line_id'), table_name='invoice_line')
    op.drop_table('invoice_line')

    op.drop_index(op.f('ix_invoice_detail_invoice_id'), table_name='invoice_detail')
    op.drop_index(op.f('ix_invoice_detail_id'), table_name='invoice_detail')
    op.drop_table('invoice_detail')
