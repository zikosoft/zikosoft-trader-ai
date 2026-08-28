"""market_data

Revision ID: 0004
Revises: 0003

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'market_bars',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('timeframe', sa.String(length=20), nullable=False),
        sa.Column('bar_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open', sa.Numeric(18, 6), nullable=True),
        sa.Column('high', sa.Numeric(18, 6), nullable=True),
        sa.Column('low', sa.Numeric(18, 6), nullable=True),
        sa.Column('close', sa.Numeric(18, 6), nullable=False),
        sa.Column('volume', sa.Numeric(20, 4), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_market_bars')),
        sa.UniqueConstraint('symbol', 'timeframe', 'bar_at', name='uq_market_bars_symbol_timeframe_bar_at'),
    )
    op.create_index(op.f('ix_market_bars_symbol'), 'market_bars', ['symbol'], unique=False)
    op.create_index(op.f('ix_market_bars_bar_at'), 'market_bars', ['bar_at'], unique=False)

    op.create_table(
        'market_quotes',
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('price', sa.Numeric(18, 6), nullable=False),
        sa.Column('raw', sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('symbol', name=op.f('pk_market_quotes')),
    )


def downgrade() -> None:
    op.drop_table('market_quotes')
    op.drop_index(op.f('ix_market_bars_bar_at'), table_name='market_bars')
    op.drop_index(op.f('ix_market_bars_symbol'), table_name='market_bars')
    op.drop_table('market_bars')
