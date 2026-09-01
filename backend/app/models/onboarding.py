from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UserOwnedMixin, uuid_pk


class OnboardingStep(Base, TimestampMixin, UserOwnedMixin):
    """§12/B07 — état persistant de chaque étape d'onboarding Alpaca.
    PENDING → RUNNING → COMPLETED (↘ FAILED). Idempotent, reprise uniquement
    sur l'étape échouée (voir B07)."""

    __tablename__ = "onboarding_steps"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_trading_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_trading_accounts.id"), nullable=True, index=True
    )
    step_code: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    error_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
