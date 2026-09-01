"""Schémas des routes kill switch (B31)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KillSwitchActionRequest(BaseModel):
    """§checklist "Confirmation renforcée" — le frontend exige déjà une
    phrase de confirmation tapée avant d'activer le bouton ; `reason` est en
    plus obligatoire côté backend (jamais uniquement une confirmation
    frontend contournable) pour qu'une action aussi lourde de conséquences
    laisse toujours une trace explicite de POURQUOI, pas seulement QUI/QUAND."""

    reason: str = Field(min_length=3, max_length=500)


class KillSwitchEventOut(BaseModel):
    action: str
    actor_user_id: uuid.UUID | None
    reason: str | None
    occurred_at: datetime
    detail: dict[str, Any]


class KillSwitchStatusOut(BaseModel):
    engaged: bool
    last_event: KillSwitchEventOut | None = None


class KillSwitchActionOut(BaseModel):
    engaged: bool
    already_engaged: bool = False
    already_disengaged: bool = False
    event: KillSwitchEventOut | None = None
    suspended_strategy_ids: list[uuid.UUID] = Field(default_factory=list)


class KillSwitchHistoryOut(BaseModel):
    events: list[KillSwitchEventOut]
