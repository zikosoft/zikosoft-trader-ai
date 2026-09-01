"""Route de lecture "ordres récents" (§B26 "Ordres récents") — même
principe d'isolation par contexte d'exécution actif que
`routers/portfolio.py` (B18) et `routers/strategy_instances.py` (B12) :
jamais d'agrégation cross-contexte (Replay et Paper ne partagent jamais
leurs chiffres, §R06). Portée strictement en lecture seule, pas de
pagination complète (juste `limit`) — le futur écran Orders complet (B25
placeholder, "backend prêt B17 UI à venir") pourra ajouter une pagination
réelle le jour où il est construit, sans que ce widget dashboard n'ait à
changer."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.errors import ErrorCode

from ..api_errors import api_error_response
from ..auth import get_current_user
from ..context import active_context, ensure_user_contexts
from ..db import get_db
from ..models import Order, User
from ..schemas.orders import OrderOut, RecentOrdersResponse

router = APIRouter(prefix="/api/orders", tags=["orders"])

MAX_RECENT_LIMIT = 50
DEFAULT_RECENT_LIMIT = 10


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


@router.get("/recent", response_model=RecentOrdersResponse)
def get_recent_orders(
    limit: int = Query(default=DEFAULT_RECENT_LIMIT, ge=1, le=MAX_RECENT_LIMIT),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    rows = db.scalars(
        select(Order)
        .where(Order.execution_context_id == context_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    ).all()
    return RecentOrdersResponse(orders=[OrderOut.model_validate(r) for r in rows])
