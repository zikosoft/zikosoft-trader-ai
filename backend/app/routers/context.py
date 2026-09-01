"""Routes des contextes d'exécution Replay/Paper (B06)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from shared.error_log import ErrorModule, log_error
from shared.errors import ErrorCode

from ..api_errors import api_error_response
from ..auth import get_current_user
from ..context import (
    SELECTABLE_KINDS,
    ContextConfirmationRequired,
    active_context,
    ensure_user_contexts,
    switch_context,
)
from ..db import engine, get_db
from ..models import User
from ..redis_client import redis_client
from ..schemas.context import ContextListResponse, ContextOut, SelectContextRequest

router = APIRouter(prefix="/api/contexts", tags=["contexts"])


def _list_response(contexts: dict) -> ContextListResponse:
    visible = [c for kind, c in contexts.items() if kind in SELECTABLE_KINDS]
    visible.sort(key=lambda c: SELECTABLE_KINDS.index(c.kind))
    active = active_context(contexts)
    return ContextListResponse(
        contexts=[ContextOut.model_validate(c) for c in visible],
        active_kind=active.kind if active else None,
    )


@router.get("", response_model=ContextListResponse)
def list_contexts(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ContextListResponse:
    contexts = ensure_user_contexts(db, user)
    return _list_response(contexts)


@router.post("/select")
def select_context(
    payload: SelectContextRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    if payload.kind not in SELECTABLE_KINDS:
        return api_error_response(
            400,
            ErrorCode.VALIDATION_ERROR,
            f"Contexte inconnu : {payload.kind!r}. Valeurs possibles : {', '.join(SELECTABLE_KINDS)}.",
        )

    try:
        _target, contexts = switch_context(
            db, redis_client, user, payload.kind, confirm=payload.confirm
        )
    except ContextConfirmationRequired as exc:
        db.rollback()
        log_error(
            engine,
            module=ErrorModule.CONTEXT,
            feature="select_context",
            severity="INFO",
            user_id=user.id,
            response_or_error="confirmation required",
            http_status=409,
            error_code=ErrorCode.CONFLICT.value,
        )
        return api_error_response(
            409,
            ErrorCode.CONFLICT,
            "Confirmation requise pour changer de contexte actif.",
            details={"active_kind": exc.active.kind, "target_kind": exc.target.kind},
        )

    db.commit()
    return JSONResponse(content=_list_response(contexts).model_dump(mode="json"))
