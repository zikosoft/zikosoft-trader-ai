"""Schémas de lecture des données de marché et des marqueurs de graphique
(§B27 "Graphiques marché et analytics") — voir `backend/app/market.py` pour
la justification complète de chaque source de données."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SymbolsResponse(BaseModel):
    symbols: list[str]


class BarOut(BaseModel):
    bar_at: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None

    model_config = {"from_attributes": True}


class BarsResponse(BaseModel):
    symbol: str
    timeframe: str
    bars: list[BarOut]


class QuoteOut(BaseModel):
    symbol: str
    price: float
    as_of: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderMarkerOut(BaseModel):
    id: uuid.UUID
    side: str
    status: str
    quantity: float | None
    notional: float | None
    filled_at: datetime | None
    submitted_at: datetime | None
    filled_price: float | None
    stop_loss: dict | None
    take_profit: dict | None


class OrderMarkersResponse(BaseModel):
    symbol: str
    orders: list[OrderMarkerOut]


class ProposalMarkerOut(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID | None
    outcome: str
    confidence: int | None
    market_data_timestamp: str | None
    reasoning_text: str | None
    created_at: datetime


class RiskEventMarkerOut(BaseModel):
    id: uuid.UUID
    agent_decision_id: uuid.UUID
    outcome: str
    reasons: list
    market_data_timestamp: str | None
    created_at: datetime


class DecisionMarkersResponse(BaseModel):
    symbol: str
    proposals: list[ProposalMarkerOut]
    risk_events: list[RiskEventMarkerOut]


class StrategyActivityOut(BaseModel):
    strategy_id: uuid.UUID
    type_code: str
    name: str
    status: str
    order_count: int
    buy_count: int
    sell_count: int
    total_notional: float


class StrategyActivityResponse(BaseModel):
    # §B27 "Performance par stratégie" — voir docstring de
    # `market.strategy_activity` : proxy honnête (activité d'ordres réels),
    # pas un P&L attribué par stratégie (non suivi à ce jour).
    strategies: list[StrategyActivityOut]
