"""Schémas Pydantic — B10 (interrupteur IA global, D026)."""

from __future__ import annotations

from pydantic import BaseModel


class AISettingsOut(BaseModel):
    enabled: bool
    max_calls_per_minute: int
    high_stakes_model: str
    low_stakes_model: str


class UpdateAISettingsRequest(BaseModel):
    enabled: bool
