"""user_experience_profile

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-30 10:00:00.000000

B30 — Profils novice/intermediate/expert :
  - colonne `users.experience_profile` (§B30 "Choix lors de l'onboarding" /
    "Modification dans Settings"), `NOT NULL DEFAULT 'novice'` — le
    démarrage le plus prudent pour tout utilisateur existant (le seul
    utilisateur démo, §D013) comme pour un futur compte V2, cohérent avec
    `PROFILE_LIMITS["novice"]` (`backend/app/profile_limits.py`) qui est
    délibérément le palier le plus restrictif.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('experience_profile', sa.String(length=20), nullable=False, server_default='novice'),
    )
    op.create_check_constraint(
        'ck_users_experience_profile',
        'users',
        "experience_profile IN ('novice', 'intermediate', 'expert')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_users_experience_profile', 'users', type_='check')
    op.drop_column('users', 'experience_profile')
