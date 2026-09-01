from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UserOwnedMixin, uuid_pk


class DashboardPreference(Base, TimestampMixin, UserOwnedMixin):
    """§13.3/B26 — préférences d'affichage (thème, disposition des widgets,
    mode Agent Room préféré — B28)."""

    __tablename__ = "dashboard_preferences"

    id: Mapped[uuid.UUID] = uuid_pk()
    theme: Mapped[str] = mapped_column(default="dark", nullable=False)
    agent_room_mode: Mapped[str] = mapped_column(default="docked", nullable=False)
    widget_layout: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
