"""Routes de lecture "résumé agents" et "résumé risque" (§B26 "Résumé Agent
Room" et "Risque") — même principe d'isolation par contexte d'exécution
actif que `routers/orders.py`/`routers/portfolio.py`. Portée strictement en
lecture seule, dernières décisions uniquement (pas de pagination complète) —
le futur Agent Room complet (B28, Live Debate/Decision Details) et Ask Ziko
AI (B29) auront besoin de bien plus (flux temps réel, citations structurées
vers une décision précise) ; ces deux routes ne visent qu'à peupler deux
petits widgets de synthèse sur le tableau de bord principal."""

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
from ..models import AgentDecision, RiskDecision, User
from ..schemas.agent_activity import (
    AgentDecisionOut,
    RecentAgentDecisionsResponse,
    RecentRiskDecisionsResponse,
    RiskDecisionOut,
)

agents_router = APIRouter(prefix="/api/agents", tags=["agents"])
risk_router = APIRouter(prefix="/api/risk", tags=["risk"])

DEFAULT_RECENT_LIMIT = 5
MAX_RECENT_LIMIT = 20


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


@agents_router.get("/decisions/recent", response_model=RecentAgentDecisionsResponse)
def get_recent_agent_decisions(
    limit: int = Query(default=DEFAULT_RECENT_LIMIT, ge=1, le=MAX_RECENT_LIMIT),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    rows = db.scalars(
        select(AgentDecision)
        .where(AgentDecision.execution_context_id == context_id)
        .order_by(AgentDecision.created_at.desc())
        .limit(limit)
    ).all()
    return RecentAgentDecisionsResponse(decisions=[AgentDecisionOut.model_validate(r) for r in rows])


@risk_router.get("/decisions/recent", response_model=RecentRiskDecisionsResponse)
def get_recent_risk_decisions(
    limit: int = Query(default=DEFAULT_RECENT_LIMIT, ge=1, le=MAX_RECENT_LIMIT),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    rows = db.scalars(
        select(RiskDecision)
        .where(RiskDecision.execution_context_id == context_id)
        .order_by(RiskDecision.created_at.desc())
        .limit(limit)
    ).all()
    return RecentRiskDecisionsResponse(decisions=[RiskDecisionOut.model_validate(r) for r in rows])
