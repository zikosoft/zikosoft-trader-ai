"""Base déclarative + conventions communes du schéma (§17 de la spec, B03) :

- UUID pour les entités métier ;
- dates en UTC (`TIMESTAMPTZ`) ;
- `user_id` sur toute donnée propriétaire (mixin `UserOwnedMixin`) ;
- `execution_context_id` sur toute donnée d'exécution (mixin `ExecutionContextMixin`) ;
- historique d'événements append-only là où précisé sur chaque table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Convention de nommage explicite : évite les noms de contraintes auto-générés
# imprévisibles, utile pour qu'Alembic produise des migrations lisibles.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # §17 — "dates en UTC" : tout `Mapped[datetime]`, dans ce modèle ou tout
    # modèle qui en hérite, devient un TIMESTAMPTZ Postgres par défaut, pas un
    # TIMESTAMP naïf. Évite d'avoir à répéter `DateTime(timezone=True)` sur
    # chaque colonne — une seule décision, appliquée partout.
    type_annotation_map = {datetime: DateTime(timezone=True)}


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserOwnedMixin:
    """Toute entité propriétaire d'un utilisateur (§17 — `user_id` obligatoire)."""

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )


class ExecutionContextMixin:
    """Toute entité d'exécution (§4.2 — `execution_context_id` obligatoire,
    filtrage systématique requis côté repository, jamais d'agrégation
    cross-contexte — voir B06 et le risque R06)."""

    execution_context_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_contexts.id"), nullable=False, index=True
    )


JSONBType = JSONB
