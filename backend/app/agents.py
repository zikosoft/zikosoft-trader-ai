from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ExecutionContextMixin, TimestampMixin, uuid_pk


class AgentDecision(Base, TimestampMixin, ExecutionContextMixin):
    """Décision structurée d'un agent (proposition Strategy Agent, critique
    Risk Critic, etc.) — historique append-only, source de vérité pour
    Decision Details (B28) et Ask Ziko AI (B29)."""

    __tablename__ = "agent_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True, index=True
    )
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(50), nullable=False)  # PROPOSAL | CRITIQUE | EXPLANATION
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    risk_flags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    market_data_timestamp: Mapped[str | None] = mapped_column(nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)


class AgentMessage(Base, ExecutionContextMixin):
    """§14.3 / D018 (B03, décision du 25/08) — persistance complète des
    échanges de l'Agent Room ("Live Debate"). Dénormalisée par design : toutes
    les infos utiles à l'affichage sont dans la ligne, pas de jointure
    obligatoire pour lire un flux. Purge manuelle en V1, pas de CRUD/admin
    (reporté en V2, non public)."""

    __tablename__ = "agent_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    conversation_thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False)  # thinking | completed | rejected | failed
    content: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # occurred_at : timestamp complet obligatoire (date + heure à la seconde, UTC),
    # jamais nullable, généré serveur — même exigence que technical_error_logs (B36).
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
