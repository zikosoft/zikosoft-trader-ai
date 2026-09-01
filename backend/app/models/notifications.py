from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UserOwnedMixin, uuid_pk


class NotificationChannel(Base, TimestampMixin, UserOwnedMixin):
    """§10.2 — configuration d'un canal (Telegram en V1). Token chiffré (B08),
    jamais retourné au frontend après sauvegarde."""

    __tablename__ = "notification_channels"

    id: Mapped[uuid.UUID] = uuid_pk()
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)  # telegram | in_app
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    encrypted_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    encryption_key_version: Mapped[int] = mapped_column(default=1, nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(20), nullable=True)


class NotificationSubscription(Base, TimestampMixin, UserOwnedMixin):
    """§10.2 — catégories d'alerte activées, sévérité minimale, quiet hours
    par canal."""

    __tablename__ = "notification_subscriptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    notification_channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_channels.id"), nullable=False, index=True
    )
    categories: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    min_severity: Mapped[str] = mapped_column(String(20), nullable=False, default="WARNING")
    quiet_hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class NotificationDelivery(Base, TimestampMixin):
    """Historique append-only des envois — statut de livraison, retries."""

    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = uuid_pk()
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id"), nullable=False, index=True
    )
    notification_channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_channels.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(nullable=True)
