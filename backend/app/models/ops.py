from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, uuid_pk


class ServiceHealthEvent(Base, TimestampMixin):
    """§11.1/B22 — changements d'état Watchdog (STARTING/HEALTHY/DEGRADED/
    DISCONNECTED/STOPPED). Append-only, alimente `/system/health`."""

    __tablename__ = "service_health_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    service_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AuditEvent(Base, TimestampMixin):
    """§19/B32 — journal d'audit (login, modification Alpaca/Telegram,
    activation stratégie, approbation, ordre, kill switch, incident).
    Append-only, jamais de secret dans `detail`."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class TechnicalErrorLog(Base):
    """Brique B36 — journal d'erreurs applicatif, dénormalisé par design
    (aucune jointure nécessaire pour déboguer). Le module Python
    `shared.error_log` insère ici via SQL brut ; ce modèle ORM sert
    essentiellement à la lecture (écran Settings → Diagnostics) et à la
    génération de la migration Alembic — les deux doivent rester alignés,
    voir le commentaire en tête de `shared/shared/error_log.py`.
    """

    __tablename__ = "technical_error_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    # occurred_at : OBLIGATOIRE, timestamptz complet (année/mois/jour/heure/
    # minute/seconde, précision milliseconde), jamais nullable, généré serveur.
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    execution_context_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    feature: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="ERROR", index=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_or_error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
