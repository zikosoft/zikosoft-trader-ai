from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ExecutionContextMixin, TimestampMixin, uuid_pk


class RiskDecision(Base, TimestampMixin, ExecutionContextMixin):
    """§7.4 — sortie du Risk Engine déterministe : APPROVED | ADJUSTED |
    REQUIRES_APPROVAL | REJECTED, avec raisons machine-readable. Append-only."""

    __tablename__ = "risk_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_decisions.id"), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # raisons machine-readable
    adjustments: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
