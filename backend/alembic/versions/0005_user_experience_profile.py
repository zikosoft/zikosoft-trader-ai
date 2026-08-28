"""user_experience_profile

Revision ID: 0005
Revises: 0004

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
