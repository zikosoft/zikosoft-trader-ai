"""Persist selected option instruments on orders.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-02

The worker already submits a validated ``OptionInstrument`` to Alpaca Paper.
This migration makes that contract durable and auditable in the Orders UI and
Agent Room, without altering historical equity orders.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A server default preserves every existing order as an equity order and
    # keeps raw SQL fixtures/backwards-compatible integrations safe.
    op.add_column(
        "orders",
        sa.Column("asset_class", sa.String(length=20), nullable=False, server_default="equity"),
    )
    op.add_column("orders", sa.Column("option_instrument", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_orders_asset_class",
        "orders",
        "asset_class IN ('equity', 'option', 'crypto')",
    )
    op.create_check_constraint(
        "ck_orders_option_instrument",
        "orders",
        "(asset_class = 'option' AND option_instrument IS NOT NULL) "
        "OR (asset_class <> 'option' AND option_instrument IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_option_instrument", "orders", type_="check")
    op.drop_constraint("ck_orders_asset_class", "orders", type_="check")
    op.drop_column("orders", "option_instrument")
    op.drop_column("orders", "asset_class")
