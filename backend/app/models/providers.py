from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UserOwnedMixin, uuid_pk


class TradingProvider(Base, TimestampMixin):
    """§9.2 — table seedée avec Alpaca, non éditable/visible depuis l'UI V1."""

    __tablename__ = "trading_providers"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UserTradingAccount(Base, TimestampMixin, UserOwnedMixin):
    """§9.2 — connecte un utilisateur au provider seedé. Secrets chiffrés
    (B08), jamais retournés en clair après sauvegarde."""

    __tablename__ = "user_trading_accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    trading_provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading_providers.id"), nullable=False, index=True
    )
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="paper")
    encrypted_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    encrypted_secret_key: Mapped[str | None] = mapped_column(String, nullable=True)
    encryption_key_version: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
