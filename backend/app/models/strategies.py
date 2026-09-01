from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ExecutionContextMixin, TimestampMixin, UserOwnedMixin, uuid_pk


class StrategyDefinition(Base, TimestampMixin):
    """§8.1/B11 — module de stratégie développeur, chargé depuis `strategies/`.
    Pas d'éditeur utilisateur, pas de JSON interne éditable (interdictions B11)."""

    __tablename__ = "strategy_definitions"

    id: Mapped[uuid.UUID] = uuid_pk()
    type_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    parameter_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ui_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    defaults_by_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    required_market_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class Strategy(Base, TimestampMixin, UserOwnedMixin, ExecutionContextMixin):
    """§8.3 — instance de stratégie créée par l'utilisateur à partir d'une
    `StrategyDefinition`. Lifecycle : DRAFT → READY → ACTIVE → PAUSED → STOPPED
    (↘ ERROR)."""

    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = uuid_pk()
    strategy_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_definitions.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(20), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    symbols: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_configuration: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    last_evaluated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    next_evaluation_at: Mapped[datetime | None] = mapped_column(nullable=True)
    latest_signal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cloned_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True
    )


class StrategyRun(Base, TimestampMixin, ExecutionContextMixin):
    """Historique append-only d'une évaluation de stratégie (une ligne par
    exécution du Strategy Agent pour une fenêtre donnée — sert notamment à
    empêcher une proposition dupliquée, voir B13)."""

    __tablename__ = "strategy_runs"
    __table_args__ = (
        UniqueConstraint("strategy_id", "window_key", name="uq_strategy_runs_window"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False, index=True
    )
    window_key: Mapped[str] = mapped_column(String(255), nullable=False)
    market_data_timestamp: Mapped[datetime] = mapped_column(nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # BUY | SELL | HOLD
    confidence: Mapped[int] = mapped_column(Integer, nullable=True)  # basis points (0-10000)
