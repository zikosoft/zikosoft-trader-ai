from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ExecutionContextMixin, TimestampMixin, UserOwnedMixin, uuid_pk


class Order(Base, TimestampMixin, UserOwnedMixin, ExecutionContextMixin):
    """§7.6/B17 — seul l'Order Worker écrit ici. Contraintes uniques contre les
    doublons (idempotency_key + client_order_id), exigence non supprimable
    (risque R05)."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "execution_context_id", "idempotency_key", name="uq_orders_idempotency"
        ),
        UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True, index=True
    )
    risk_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_decisions.id"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # buy | sell
    notional: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False, default="market")
    time_in_force: Mapped[str] = mapped_column(String(10), nullable=False, default="day")
    stop_loss: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    take_profit: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # X-Request-ID
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(nullable=True)


class OrderEvent(Base, ExecutionContextMixin):
    """Historique append-only des changements de statut d'un ordre
    (order.status.changed, §5.3)."""

    __tablename__ = "order_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
