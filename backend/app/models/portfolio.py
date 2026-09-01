from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ExecutionContextMixin, TimestampMixin, UserOwnedMixin, uuid_pk


class PositionSnapshot(Base, TimestampMixin, UserOwnedMixin, ExecutionContextMixin):
    """§18/B18 — snapshot périodique des positions ouvertes."""

    __tablename__ = "positions_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    average_entry_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    market_value: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    unrealized_pl: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(nullable=False, index=True)


class PortfolioSnapshot(Base, TimestampMixin, UserOwnedMixin, ExecutionContextMixin):
    """§18/B18 — snapshot périodique du compte (cash, buying power, valeur,
    P&L). Alimente les cartes 1D–7D et l'historique (90 jours max côté UI)."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    cash: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    buying_power: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    portfolio_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    daily_pl: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    total_pl: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    raw_provider_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
