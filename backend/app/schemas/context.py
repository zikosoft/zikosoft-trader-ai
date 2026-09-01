"""Schémas Pydantic — B06 (contextes Replay/Paper)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ContextOut(BaseModel):
    id: uuid.UUID
    kind: str
    label: str
    is_active: bool

    model_config = {"from_attributes": True}


class ContextListResponse(BaseModel):
    contexts: list[ContextOut]
    active_kind: str | None


class SelectContextRequest(BaseModel):
    # Validité (PAPER/REPLAY uniquement, pas DRY_RUN) vérifiée dans la route
    # plutôt qu'ici avec un validator Pydantic : on veut renvoyer notre
    # format d'erreur commun (`ErrorCode.VALIDATION_ERROR`, §B01), pas le
    # 422 par défaut de FastAPI pour une erreur de validation Pydantic.
    kind: str = Field(min_length=1, max_length=20)
    confirm: bool = False
