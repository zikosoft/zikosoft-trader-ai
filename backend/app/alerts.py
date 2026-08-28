from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ExecutionContextMixin, TimestampMixin, UserOwnedMixin, uuid_pk


class Alert(Base, TimestampMixin, UserOwnedMixin, ExecutionContextMixin):
    """§10 — modèle standard d'alerte (catégorie, sévérité), source des
    notifications in-app (B20) et Telegram (B21) via l'Alert Dispatcher."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = uuid_pk()
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(nullable=False)
    related_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dedup_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
