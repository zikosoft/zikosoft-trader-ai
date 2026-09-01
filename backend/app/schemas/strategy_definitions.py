"""Schémas de sortie de l'API de lecture du registre de stratégies (B11)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class StrategyDefinitionOut(BaseModel):
    id: uuid.UUID
    type_code: str
    version: str
    name: str
    description: str
    parameter_schema: dict
    ui_schema: dict
    defaults_by_profile: dict
    required_market_data: dict
    required_capabilities: list[str]
