"""Schémas Pydantic — B07 (onboarding Alpaca)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ConnectRequest(BaseModel):
    # Alpaca émet des clés d'une trentaine de caractères ; les bornes ici ne
    # visent qu'à rejeter un champ vide ou un copier-coller manifestement
    # cassé avant même d'appeler Alpaca — la vraie validation est l'appel
    # réel à `GET /v2/account` (§B07 "clé invalide rejetée clairement").
    api_key: str = Field(min_length=1, max_length=255)
    secret_key: str = Field(min_length=1, max_length=255)


class BalanceOut(BaseModel):
    cash: float
    buying_power: float
    portfolio_value: float
    snapshot_at: datetime


class StepOut(BaseModel):
    step_code: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error_details: dict | None

    model_config = {"from_attributes": True}


class AccountOut(BaseModel):
    id: uuid.UUID
    environment: str
    status: str
    external_account_id: str | None
    last_synced_at: datetime | None
    balance: BalanceOut | None = None

    model_config = {"from_attributes": True}


class OnboardingStatusResponse(BaseModel):
    account: AccountOut | None
    steps: list[StepOut]
