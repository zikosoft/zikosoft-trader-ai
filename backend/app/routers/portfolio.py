"""Routes de lecture du portefeuille (B18) — résumé compte, positions
ouvertes, historique paginé, cartes de performance 1D-7D. Isolation totale
par contexte d'exécution actif (même principe que
`routers/strategy_instances.py`, B12) : jamais d'agrégation cross-contexte
(Replay et Paper ne partagent jamais leurs chiffres, §R06).

Portée volontairement backend-only (§B18, voir AVANCEMENT.md) : pas de
carte dashboard ici — B26 (Dashboard principal) consommera ces routes.
Cache Redis court (`settings.portfolio_cache_ttl_seconds`) sur les deux
lectures les plus susceptibles d'un polling fréquent depuis un futur
frontend (résumé, positions) — pas sur `/history`, moins sollicité et dont
la pagination (`offset`) rendrait un cache par clé peu utile."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from shared.errors import ErrorCode

from .. import portfolio as service
from ..api_errors import api_error_response
from ..auth import get_current_user
from ..config import settings
from ..context import active_context, ensure_user_contexts
from ..db import get_db
from ..models import User
from ..redis_client import redis_client
from ..schemas.portfolio import (
    PerformanceCardOut,
    PerformanceCardsResponse,
    PortfolioHistoryItemOut,
    PortfolioHistoryResponse,
    PortfolioSummaryOut,
    PositionOut,
    PositionsResponse,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

MAX_HISTORY_LIMIT = 200


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


def _cache_get(key: str) -> dict | None:
    raw = redis_client.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _cache_set(key: str, value: dict) -> None:
    if settings.portfolio_cache_ttl_seconds <= 0:
        return
    redis_client.set(key, json.dumps(value), ex=int(settings.portfolio_cache_ttl_seconds))


@router.get("/summary", response_model=PortfolioSummaryOut)
def get_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    cache_key = f"portfolio:summary:{context_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return PortfolioSummaryOut.model_validate(cached)

    snapshot = service.latest_snapshot(db, execution_context_id=context_id)
    if snapshot is None:
        # §B18 — honnête : "pas encore de portefeuille" n'est pas une erreur
        # serveur, c'est un état réel (worker pas encore passé, ou compte
        # Alpaca pas encore connecté) — jamais fabriqué comme un résumé à
        # zéro qui prétendrait représenter un vrai compte.
        return api_error_response(
            404, ErrorCode.NOT_FOUND, "aucun portefeuille disponible pour ce contexte pour l'instant"
        )

    out = PortfolioSummaryOut.model_validate(snapshot)
    _cache_set(cache_key, out.model_dump(mode="json"))
    return out


@router.get("/positions", response_model=PositionsResponse)
def get_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    cache_key = f"portfolio:positions:{context_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return PositionsResponse.model_validate(cached)

    rows, snapshot_at = service.latest_positions(db, execution_context_id=context_id)
    out = PositionsResponse(positions=[PositionOut.model_validate(r) for r in rows], snapshot_at=snapshot_at)
    _cache_set(cache_key, out.model_dump(mode="json"))
    return out


@router.get("/history", response_model=PortfolioHistoryResponse)
def get_history(
    days: int = Query(default=service.DEFAULT_HISTORY_DAYS, ge=1, le=service.DEFAULT_HISTORY_DAYS),
    limit: int = Query(default=50, ge=1, le=MAX_HISTORY_LIMIT),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    rows, total = service.history(db, execution_context_id=context_id, days=days, limit=limit, offset=offset)
    return PortfolioHistoryResponse(
        items=[PortfolioHistoryItemOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/performance", response_model=PerformanceCardsResponse)
def get_performance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    cache_key = f"portfolio:performance:{context_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return PerformanceCardsResponse.model_validate(cached)

    cards = service.performance_cards(db, execution_context_id=context_id)
    out = PerformanceCardsResponse(cards=[PerformanceCardOut(**c) for c in cards])
    _cache_set(cache_key, out.model_dump(mode="json"))
    return out
