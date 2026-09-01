"""Routes de lecture/acquittement des alertes in-app (B20 — Alert
Dispatcher). Même principe d'isolation par contexte d'exécution actif que
`routers/orders.py`/`routers/portfolio.py` (§R06 "jamais d'agrégation
cross-contexte") pour la LECTURE (`GET /alerts`, `GET /unread-count`) —
une alerte Paper n'apparaît jamais pendant qu'on consulte Replay, et
inversement. Les mutations (`POST .../read`, `POST .../read-all`) restent
scopées au contexte actif pour la même raison (pas de "tout marquer lu"
qui acquitterait silencieusement des alertes d'un autre contexte)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from shared.errors import ErrorCode

from ..api_errors import api_error_response
from ..auth import get_current_user
from ..context import active_context, ensure_user_contexts
from ..db import get_db
from ..models import Alert, User
from ..schemas.alerts import AlertListResponse, AlertOut, MarkReadResponse, UnreadCountResponse

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

MAX_LIMIT = 100
DEFAULT_LIMIT = 20


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


@router.get("", response_model=AlertListResponse)
def list_alerts(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    query = select(Alert).where(Alert.user_id == user.id, Alert.execution_context_id == context_id)
    if unread_only:
        query = query.where(Alert.is_read.is_(False))

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()
    rows = (
        db.execute(query.order_by(Alert.created_at.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )
    return AlertListResponse(alerts=[AlertOut.model_validate(r, from_attributes=True) for r in rows], total=total)


@router.get("/unread-count", response_model=UnreadCountResponse)
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    count = db.execute(
        select(func.count()).select_from(Alert).where(
            Alert.user_id == user.id,
            Alert.execution_context_id == context_id,
            Alert.is_read.is_(False),
        )
    ).scalar_one()
    return UnreadCountResponse(unread_count=count)


@router.post("/{alert_id}/read", response_model=MarkReadResponse)
def mark_read(alert_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = db.execute(
        update(Alert)
        .where(Alert.id == alert_id, Alert.user_id == user.id, Alert.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return MarkReadResponse(updated_count=result.rowcount or 0)


@router.post("/read-all", response_model=MarkReadResponse)
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    result = db.execute(
        update(Alert)
        .where(Alert.user_id == user.id, Alert.execution_context_id == context_id, Alert.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return MarkReadResponse(updated_count=result.rowcount or 0)
