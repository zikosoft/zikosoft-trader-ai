"""Routes CRUD d'instances de stratégie (B12 "CRUD instances") — construit
sur le registre B11 (`StrategyDefinition` en base) et le contexte
d'exécution actif de l'utilisateur (B06). Toute route ici exige un contexte
actif (Paper ou Replay déjà sélectionné, voir `POST /api/contexts/select`),
cohérent avec le principe d'isolation totale entre contextes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from shared.errors import ErrorCode

from .. import strategy_instances as service
from ..api_errors import api_error_response
from ..auth import get_current_user
from ..context import active_context, ensure_user_contexts
from ..db import get_db
from ..models import StrategyDefinition, User
from ..schemas.strategy_instances import (
    CloneStrategyInstanceRequest,
    CreateStrategyInstanceRequest,
    StrategyInstanceOut,
    UpdateStrategyInstanceRequest,
)

router = APIRouter(prefix="/api/strategies/instances", tags=["strategies"])


class _NoActiveContext(Exception):
    pass


def _require_active_context_id(db: Session, user: User) -> uuid.UUID:
    contexts = ensure_user_contexts(db, user)
    active = active_context(contexts)
    if active is None:
        raise _NoActiveContext()
    return active.id


_ERROR_STATUS = {
    service.StrategyDefinitionNotFound: (404, ErrorCode.NOT_FOUND),
    service.StrategyInstanceNotFound: (404, ErrorCode.NOT_FOUND),
    service.StrategyParametersInvalid: (400, ErrorCode.VALIDATION_ERROR),
    service.StrategyLimitExceeded: (409, ErrorCode.CONFLICT),
    service.StrategyInvalidTransition: (409, ErrorCode.CONFLICT),
    service.StrategyDeletionBlocked: (409, ErrorCode.CONFLICT),
}


def _call_service(db: Session, user: User, fn, *args, **kwargs):
    """Résout le contexte actif puis appelle `fn(db, user, context_id, ...)`,
    en normalisant toutes les erreurs métier (contexte manquant, définition
    introuvable, paramètres invalides, limites produit, transition de
    statut interdite, suppression bloquée) dans le format d'erreur commun —
    un seul endroit à maintenir plutôt qu'un `try/except` dupliqué dans
    chacune des 8 routes ci-dessous."""
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return None, api_error_response(400, ErrorCode.VALIDATION_ERROR, "aucun contexte d'exécution actif")

    try:
        result = fn(db, user, context_id, *args, **kwargs)
        return result, None
    except tuple(_ERROR_STATUS) as exc:
        status_code, code = _ERROR_STATUS[type(exc)]
        details = {"errors": exc.errors} if isinstance(exc, service.StrategyParametersInvalid) else None
        return None, api_error_response(status_code, code, str(exc), details=details)


def _to_out(db: Session, instance) -> StrategyInstanceOut:
    definition = db.get(StrategyDefinition, instance.strategy_definition_id)
    return StrategyInstanceOut(
        id=instance.id,
        strategy_definition_id=instance.strategy_definition_id,
        type_code=definition.type_code if definition else "",
        name=instance.name,
        definition_version=instance.definition_version,
        parameters=instance.parameters,
        symbols=instance.symbols,
        risk_configuration=instance.risk_configuration,
        status=instance.status,
        last_evaluated_at=instance.last_evaluated_at,
        next_evaluation_at=instance.next_evaluation_at,
        latest_signal=instance.latest_signal,
        cloned_from_id=instance.cloned_from_id,
        execution_context_id=instance.execution_context_id,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


@router.post("", response_model=StrategyInstanceOut, status_code=201)
def create_instance(
    payload: CreateStrategyInstanceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result, error = _call_service(
        db,
        user,
        service.create_instance,
        type_code=payload.type_code,
        name=payload.name,
        symbols=payload.symbols,
        parameters=payload.parameters,
        risk_configuration=payload.risk_configuration,
    )
    return error if error is not None else _to_out(db, result)


@router.get("", response_model=list[StrategyInstanceOut])
def list_instances(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result, error = _call_service(db, user, service.list_instances)
    return error if error is not None else [_to_out(db, instance) for instance in result]


@router.get("/{instance_id}", response_model=StrategyInstanceOut)
def get_instance(instance_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result, error = _call_service(db, user, service.get_instance, instance_id)
    return error if error is not None else _to_out(db, result)


@router.patch("/{instance_id}", response_model=StrategyInstanceOut)
def update_instance(
    instance_id: uuid.UUID,
    payload: UpdateStrategyInstanceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result, error = _call_service(
        db,
        user,
        service.update_instance,
        instance_id,
        name=payload.name,
        symbols=payload.symbols,
        parameters=payload.parameters,
        risk_configuration=payload.risk_configuration,
    )
    return error if error is not None else _to_out(db, result)


@router.post("/{instance_id}/clone", response_model=StrategyInstanceOut, status_code=201)
def clone_instance(
    instance_id: uuid.UUID,
    payload: CloneStrategyInstanceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result, error = _call_service(db, user, service.clone_instance, instance_id, new_name=payload.name)
    return error if error is not None else _to_out(db, result)


@router.post("/{instance_id}/activate", response_model=StrategyInstanceOut)
def activate_instance(instance_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result, error = _call_service(db, user, service.activate_instance, instance_id)
    return error if error is not None else _to_out(db, result)


@router.post("/{instance_id}/pause", response_model=StrategyInstanceOut)
def pause_instance(instance_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result, error = _call_service(db, user, service.pause_instance, instance_id)
    return error if error is not None else _to_out(db, result)


@router.post("/{instance_id}/stop", response_model=StrategyInstanceOut)
def stop_instance(instance_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result, error = _call_service(db, user, service.stop_instance, instance_id)
    return error if error is not None else _to_out(db, result)


@router.delete("/{instance_id}", status_code=204)
def delete_instance(instance_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _, error = _call_service(db, user, service.delete_instance, instance_id)
    return error if error is not None else JSONResponse(status_code=204, content=None)
