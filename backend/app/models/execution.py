from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UserOwnedMixin, uuid_pk


class ExecutionContext(Base, TimestampMixin, UserOwnedMixin):
    """§4.2 — PAPER / REPLAY / DRY_RUN. Toute table d'exécution référence
    cette table via `execution_context_id` (ExecutionContextMixin). Le
    filtrage par contexte est obligatoire côté repository, jamais
    d'agrégation cross-contexte (risque R06, non supprimable).

    B06 : `is_active` est le contexte actuellement sélectionné par
    l'utilisateur — au plus un actif à la fois. Contrainte posée en base
    (index unique partiel `uq_execution_contexts_one_active_per_user`,
    migration 0003) plutôt que côté application seulement : une contrainte
    DB reste vraie même en cas de bug applicatif ou de requêtes concurrentes,
    l'application seule ne peut pas le garantir de façon fiable."""

    __tablename__ = "execution_contexts"
    __table_args__ = (
        CheckConstraint("kind IN ('PAPER', 'REPLAY', 'DRY_RUN')", name="ck_execution_contexts_kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # PAPER | REPLAY | DRY_RUN
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ExecutionContextSwitch(Base):
    """B06 — historique append-only des changements de contexte (audit +
    support de la « confirmation avant changement »). Une ligne par
    changement effectif ; le premier choix après login (aucun contexte
    encore actif) a `from_context_id` NULL et ne requiert pas de
    confirmation (`confirmed` reste `false` dans ce cas, il n'y avait rien à
    confirmer)."""

    __tablename__ = "execution_context_switches"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    from_context_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_contexts.id"), nullable=True
    )
    to_context_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_contexts.id"), nullable=False, index=True
    )
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    switched_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
