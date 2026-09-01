"""Routes de lecture des données de marché et des marqueurs de graphique
(§B27 "Graphiques marché et analytics") — voir `backend/app/market.py` pour
la provenance de chaque donnée. `symbols`/`bars`/`quote` ne sont PAS scopées
par contexte d'exécution (donnée de marché, identique pour tous les
contextes, voir `backend/app/models/market_data.py`) ; `orders`/`decisions`/
`strategy-activity` le sont (mêmes principes d'isolation que
`routers/portfolio.py`/`routers/orders.py`, §R06)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from shared.errors import ErrorCode

from .. import market as service
from ..api_errors import api_error_response
from ..auth import get_current_user
from ..context import active_context, ensure_user_contexts
from ..db import get_db
from ..models import User
from ..schemas.market import (
    BarOut,
    BarsResponse,
    DecisionMarkersResponse,
    OrderMarkerOut,
    OrderMarkersResponse,
    ProposalMarkerOut,
    QuoteOut,
    RiskEventMarkerOut,
    StrategyActivityOut,
    StrategyActivityResponse,
    SymbolsResponse,
)

router = APIRouter(prefix="/api/market", tags=["market"])

DEFAULT_TIMEFRAME = "1Day"


class _NoActiveContext(Exception):
    pass


def _require_active_context_id(db: Session, user: User) -> uuid.UUID:
    contexts = ensure_user_contexts(db, user)
    active = active_context(contexts)
    if active is None:
        raise _NoActiveContext()
    return active.id


def _no_active_context_error() -> JSONResponse:
    return api_error_response(400, ErrorCode.VALIDATION_ERROR, "aucun contexte d'exécution actif")


@router.get("/symbols", response_model=SymbolsResponse)
def get_symbols(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return SymbolsResponse(symbols=service.list_symbols(db))


@router.get("/bars", response_model=BarsResponse)
def get_bars(
    symbol: str,
    timeframe: str = Query(default=DEFAULT_TIMEFRAME),
    limit: int = Query(default=service.DEFAULT_BARS_LIMIT, ge=1, le=service.MAX_BARS_LIMIT),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    symbol = symbol.upper()
    bars = service.list_bars(db, symbol=symbol, timeframe=timeframe, limit=limit)
    return BarsResponse(symbol=symbol, timeframe=timeframe, bars=[BarOut.model_validate(b) for b in bars])


@router.get("/quote", response_model=QuoteOut)
def get_quote(symbol: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    symbol = symbol.upper()
    quote = service.latest_quote(db, symbol=symbol)
    if quote is None:
        # §D009/ColdStartView même discipline — "pas encore de cotation" est
        # un état réel (agent pas encore passé, ou symbole hors watchlist),
        # jamais un prix fabriqué à zéro.
        return api_error_response(404, ErrorCode.NOT_FOUND, "aucune cotation disponible pour ce symbole pour l'instant")
    return QuoteOut.model_validate(quote)


@router.get("/orders", response_model=OrderMarkersResponse)
def get_order_markers(
    symbol: str,
    limit: int = Query(default=service.DEFAULT_MARKERS_LIMIT, ge=1, le=service.MAX_MARKERS_LIMIT),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    symbol = symbol.upper()
    markers = service.list_order_markers(db, execution_context_id=context_id, symbol=symbol, limit=limit)
    return OrderMarkersResponse(symbol=symbol, orders=[OrderMarkerOut(**m) for m in markers])


@router.get("/decisions", response_model=DecisionMarkersResponse)
def get_decision_markers(
    symbol: str,
    limit: int = Query(default=service.DEFAULT_MARKERS_LIMIT, ge=1, le=service.MAX_MARKERS_LIMIT),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    symbol = symbol.upper()
    proposals, risk_rows = service.list_decision_markers(
        db, execution_context_id=context_id, symbol=symbol, limit=limit
    )
    return DecisionMarkersResponse(
        symbol=symbol,
        proposals=[
            ProposalMarkerOut(
                id=p.id,
                strategy_id=p.strategy_id,
                outcome=p.outcome,
                confidence=p.confidence,
                market_data_timestamp=p.market_data_timestamp,
                reasoning_text=(p.reasoning or {}).get("text"),
                created_at=p.created_at,
            )
            for p in proposals
        ],
        risk_events=[
            RiskEventMarkerOut(
                id=r.id,
                agent_decision_id=r.agent_decision_id,
                outcome=r.outcome,
                reasons=r.reasons,
                market_data_timestamp=d.market_data_timestamp,
                created_at=r.created_at,
            )
            for r, d in risk_rows
        ],
    )


@router.get("/strategy-activity", response_model=StrategyActivityResponse)
def get_strategy_activity(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    rows = service.strategy_activity(db, execution_context_id=context_id)
    return StrategyActivityResponse(strategies=[StrategyActivityOut(**r) for r in rows])
