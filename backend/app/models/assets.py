from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, uuid_pk


class Asset(Base, TimestampMixin):
    """§9.3 — catalogue canonique, indépendant du provider."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    canonical_symbol: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)  # equity | etf | crypto | option
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class ProviderAsset(Base, TimestampMixin):
    """§9.3 — mapping symbole canonique <-> symbole provider (Alpaca en V1)."""

    __tablename__ = "provider_assets"
    __table_args__ = (UniqueConstraint("provider_id", "provider_symbol", name="uq_provider_symbol"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading_providers.id"), nullable=False, index=True
    )
    provider_asset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    tradable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fractionable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    shortable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
