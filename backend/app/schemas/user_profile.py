"""Schémas Pydantic — B30 (profils novice/intermediate/expert)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ExperienceProfile = Literal["novice", "intermediate", "expert"]


class ProfileLimitsOut(BaseModel):
    max_active_strategies: int
    max_symbols: int
    order_risk_pct: float
    daily_loss_pct: float
    approval_mode: str


class UserProfileOut(BaseModel):
    profile: ExperienceProfile
    limits: ProfileLimitsOut


class UpdateUserProfileRequest(BaseModel):
    profile: ExperienceProfile
