from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, uuid_pk


class User(Base, TimestampMixin):
    """Utilisateur applicatif. Un seul utilisateur démo est exposé en V1
    (§9.1 de la spec), mais le modèle est user-aware dès le socle pour rester
    compatible avec l'évolution multi-utilisateur privée (V2, non publique)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Demo User")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    # §B30 — novice | intermediate | expert (voir `app/profile_limits.py`
    # pour la grille de limites associée). `NOT NULL DEFAULT 'novice'`
    # posé par la migration 0005 — palier le plus prudent par défaut.
    experience_profile: Mapped[str] = mapped_column(String(20), nullable=False, default="novice")


class UserSession(Base, TimestampMixin):
    """Session d'authentification (B05). Un enregistrement par connexion
    réussie ; le cookie envoyé au navigateur contient un jeton opaque
    aléatoire (32 octets, urlsafe) — seul son hash SHA-256 (`token_hash`) est
    stocké ici, jamais le jeton en clair, pour qu'une fuite de la base ne
    permette pas de rejouer une session active (même principe que le
    hachage des mots de passe). La déconnexion pose `revoked_at` plutôt que
    de supprimer la ligne (traçabilité, cohérent avec l'esprit append-only
    du reste du schéma) ; une session révoquée ou expirée est refusée par
    `get_current_user`, quel que soit le jeton présenté."""

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(nullable=True)
