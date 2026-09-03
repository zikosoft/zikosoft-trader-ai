"""Schémas Pydantic — B10 (interrupteur IA global, D026)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AISettingsOut(BaseModel):
    enabled: bool
    max_calls_per_minute: int
    max_calls_per_day: int
    high_stakes_model: str
    low_stakes_model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    daily_budget_usd: float
    # Read-only value from deployment configuration. It has no corresponding
    # field in UpdateAISettingsRequest, so a browser can never raise it.
    daily_budget_hard_cap_usd: float
    # Read-only accounting values. They are UTC-day reservations made before
    # provider requests, never API-key or prompt data.
    daily_budget_reserved_usd: float
    daily_budget_remaining_usd: float
    daily_calls_reserved: int
    daily_budget_reset_at: datetime
    api_key_configured: bool


class UpdateAISettingsRequest(BaseModel):
    enabled: bool
    max_calls_per_minute: int | None = Field(default=None, ge=1, le=10_000)
    max_calls_per_day: int | None = Field(default=None, ge=1, le=1_000_000)
    high_stakes_model: str | None = Field(default=None, min_length=1, max_length=120)
    low_stakes_model: str | None = Field(default=None, min_length=1, max_length=120)
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=128, le=32_000)
    timeout_seconds: float | None = Field(default=None, ge=1.0, le=120.0)
    daily_budget_usd: float | None = Field(default=None, ge=0.0, le=10_000.0)
    # Write-only: never returned by AISettingsOut and never logged.
    api_key: str | None = Field(default=None, max_length=512)
