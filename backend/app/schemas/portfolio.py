"""Schémas Pydantic — B18 (Portefeuille, positions et historique)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PortfolioSummaryOut(BaseModel):
    cash: float
    buying_power: float
    portfolio_value: float
    # §B18 — honnêtement `None` tant que le worker n'a pas encore au moins
    # deux tours pour `daily_pl` (voir `_compute_daily_pl`), ou aucun
    # snapshot antérieur pour `total_pl` — jamais fabriqués.
    daily_pl: float | None
    total_pl: float | None
    snapshot_at: datetime

    model_config = {"from_attributes": True}


class PositionOut(BaseModel):
    symbol: str
    quantity: float
    average_entry_price: float | None
    market_value: float | None
    unrealized_pl: float | None
    snapshot_at: datetime

    model_config = {"from_attributes": True}


class PositionsResponse(BaseModel):
    positions: list[PositionOut]
    # `None` si aucun tour de positions n'a encore été écrit pour ce
    # contexte — distinct de "compte sans aucune position ouverte" (auquel
    # cas `snapshot_at` est renseigné mais `positions` est vide).
    snapshot_at: datetime | None


class PortfolioHistoryItemOut(BaseModel):
    cash: float
    buying_power: float
    portfolio_value: float
    daily_pl: float | None
    total_pl: float | None
    snapshot_at: datetime

    model_config = {"from_attributes": True}


class PortfolioHistoryResponse(BaseModel):
    items: list[PortfolioHistoryItemOut]
    total: int
    limit: int
    offset: int


class PerformanceCardOut(BaseModel):
    # "1D", "3D", "7D" (§B18 "Cartes 1D à 7D").
    window: str
    available: bool
    # Toujours "Not enough account history yet" quand `available=False` —
    # texte exact du libellé §18 de la spec, jamais une variation fabriquée.
    reason: str | None = None
    value_change: float | None = None
    percent_change: float | None = None


class PerformanceCardsResponse(BaseModel):
    cards: list[PerformanceCardOut]
