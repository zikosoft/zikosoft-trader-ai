"""Schémas des routes CRUD d'instances de stratégie (B12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateStrategyInstanceRequest(BaseModel):
    type_code: str
    name: str = Field(min_length=1, max_length=255)
    symbols: list[str] = Field(min_length=1)
    parameters: dict[str, Any]
    risk_configuration: dict[str, Any] = Field(default_factory=dict)


class UpdateStrategyInstanceRequest(BaseModel):
    """Toutes les propriétés sont optionnelles — mise à jour partielle,
    seuls les champs fournis sont modifiés."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    symbols: list[str] | None = None
    parameters: dict[str, Any] | None = None
    risk_configuration: dict[str, Any] | None = None


class CloneStrategyInstanceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class StrategyInstanceOut(BaseModel):
    id: uuid.UUID
    strategy_definition_id: uuid.UUID
    type_code: str
    name: str
    definition_version: str
    parameters: dict[str, Any]
    symbols: list[str]
    risk_configuration: dict[str, Any]
    status: str
    last_evaluated_at: datetime | None
    next_evaluation_at: datetime | None
    latest_signal: str | None
    cloned_from_id: uuid.UUID | None
    execution_context_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
