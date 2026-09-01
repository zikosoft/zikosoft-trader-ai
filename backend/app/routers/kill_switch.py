"""Routes du kill switch trading (§B31). Volontairement GLOBALES — pas
scopées par contexte d'exécution actif, contrairement à la quasi-totalité
du reste de l'API (§R06) : le flag lui-même (`shared.risk_governance`,
B15/D031) n'a jamais été scopé par contexte, et le Risk Engine l'applique
sans distinction Paper/Replay — même portée retenue ici, cohérence oblige."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from shared.errors import ErrorCode

from .. import kill_switch as service
from ..api_errors import api_error_response
from ..auth import get_current_user
from ..db import get_db
from ..models import User
from ..redis_client import redis_client
from ..schemas.kill_switch import (
    KillSwitchActionOut,
    KillSwitchActionRequest,
    KillSwitchHistoryOut,
    KillSwitchStatusOut,
)

router = APIRouter(prefix="/api/system/kill-switch", tags=["system"])


@router.get("/status", response_model=KillSwitchStatusOut)
def get_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return KillSwitchStatusOut(**service.status_detail(db, redis_client))


@router.get("/history", response_model=KillSwitchHistoryOut)
def get_history(limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return KillSwitchHistoryOut(events=service.history(db, limit=min(max(limit, 1), 100)))


@router.post("/engage", response_model=KillSwitchActionOut)
def engage(
    payload: KillSwitchActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.engage(db, redis_client, actor=user, reason=payload.reason)
    except service.KillSwitchReasonRequired:
        return _reason_required_error()
    return KillSwitchActionOut(**result)


@router.post("/disengage", response_model=KillSwitchActionOut)
def disengage(
    payload: KillSwitchActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.disengage(db, redis_client, actor=user, reason=payload.reason)
    except service.KillSwitchReasonRequired:
        return _reason_required_error()
    return KillSwitchActionOut(**result)


def _reason_required_error() -> JSONResponse:
    return api_error_response(400, ErrorCode.VALIDATION_ERROR, "une raison est obligatoire pour cette action")
