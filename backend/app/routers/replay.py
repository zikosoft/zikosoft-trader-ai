"""Routes du Replay Engine (B19, Étape A — squelette minimal). Dataset fixe
chargé depuis disque (voir `scripts/fetch_replay_dataset.py` et
`shared/shared/replay_market_data.py`), lecture x1 simple (pas de
vitesses x2/x5/x10 — ça, c'est l'Étape B, après B11-B17, voir la
"Séquencement révisé" dans AVANCEMENT.md).

Isolation par contexte : ces routes exigent un contexte REPLAY actif (même
principe que `routers/portfolio.py`/`routers/strategy_instances.py`) — un
utilisateur en Paper ne peut pas piloter une session Replay par erreur.

Statelessness délibérée : chaque requête HTTP reconstruit un
`ReplayMarketDataProvider` neuf (rien n'est gardé en mémoire process) — la
position courante est restaurée depuis Redis (`shared/shared/replay_state.py`)
via `provider.seek(index)`. Pas de cache de dataset au niveau module : le
chargement est bon marché (une journée, quelques symboles, JSON + checksum)
et un cache mal invalidé risquerait de servir un dataset périmé après un
nouveau passage de `fetch_replay_dataset.py`."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from shared.errors import ErrorCode
from shared.replay_market_data import (
    DEFAULT_REPLAY_DATASET_PATH,
    ReplayDataset,
    ReplayDatasetError,
    ReplayMarketDataProvider,
    load_dataset,
)
from shared.replay_state import clear_replay_session, get_replay_session, set_replay_session

from ..api_errors import api_error_response
from ..auth import get_current_user
from ..config import settings
from ..context import active_context, ensure_user_contexts
from ..db import get_db
from ..models import User
from ..redis_client import redis_client
from ..schemas.replay import ReplayBarOut, ReplayDatasetOut, ReplaySessionOut

router = APIRouter(prefix="/api/replay", tags=["replay"])


class _NoActiveReplayContext(Exception):
    pass


def _require_active_replay_context_id(db: Session, user: User) -> uuid.UUID:
    contexts = ensure_user_contexts(db, user)
    active = active_context(contexts)
    if active is None or active.kind != "REPLAY":
        raise _NoActiveReplayContext()
    return active.id


def _no_active_replay_context_error() -> JSONResponse:
    return api_error_response(400, ErrorCode.VALIDATION_ERROR, "aucun contexte REPLAY actif")


def _dataset_path() -> Path:
    return Path(settings.replay_dataset_path) if settings.replay_dataset_path else DEFAULT_REPLAY_DATASET_PATH


def _dataset_not_found_error(exc: ReplayDatasetError) -> JSONResponse:
    # §honnêteté (D021/D047) — aucun dataset de secours fabriqué : si le
    # fichier est absent ou corrompu, on le dit, on ne simule rien.
    return api_error_response(404, ErrorCode.NOT_FOUND, str(exc))


def _session_out(dataset: ReplayDataset, provider: ReplayMarketDataProvider) -> ReplaySessionOut:
    bars = provider.current_bars()
    return ReplaySessionOut(
        dataset_id=dataset.dataset_id,
        trading_day=dataset.trading_day,
        symbols=list(dataset.symbols),
        total_bars=len(dataset.timestamps),
        current_index=provider.index,
        current_timestamp=provider.current_timestamp(),
        current_bars={symbol: ReplayBarOut(**bar.to_dict()) for symbol, bar in bars.items()},
        is_finished=provider.is_finished,
    )


@router.get("/dataset", response_model=ReplayDatasetOut)
def get_dataset_info(user: User = Depends(get_current_user)):
    try:
        dataset = load_dataset(_dataset_path())
    except ReplayDatasetError as exc:
        return _dataset_not_found_error(exc)

    return ReplayDatasetOut(
        dataset_id=dataset.dataset_id,
        trading_day=dataset.trading_day,
        timezone=dataset.timezone,
        symbols=list(dataset.symbols),
        total_bars=len(dataset.timestamps),
        checksum=dataset.checksum,
    )


@router.post("/session/reset", response_model=ReplaySessionOut)
def reset_session(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context_id = _require_active_replay_context_id(db, user)
    except _NoActiveReplayContext:
        return _no_active_replay_context_error()

    try:
        dataset = load_dataset(_dataset_path())
    except ReplayDatasetError as exc:
        return _dataset_not_found_error(exc)

    # §restart déterministe — on efface toute session précédente plutôt que
    # de laisser un vieil index traîner sous une clé qu'on ne va pas relire.
    clear_replay_session(redis_client, context_id)
    provider = ReplayMarketDataProvider(dataset)
    set_replay_session(redis_client, context_id, dataset_id=dataset.dataset_id, index=provider.index)
    return _session_out(dataset, provider)


@router.post("/session/advance", response_model=ReplaySessionOut)
def advance_session(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context_id = _require_active_replay_context_id(db, user)
    except _NoActiveReplayContext:
        return _no_active_replay_context_error()

    try:
        dataset = load_dataset(_dataset_path())
    except ReplayDatasetError as exc:
        return _dataset_not_found_error(exc)

    provider = ReplayMarketDataProvider(dataset)
    session = get_replay_session(redis_client, context_id)
    if session is not None and session["dataset_id"] == dataset.dataset_id:
        provider.seek(session["index"])
    # Si aucune session n'existe encore, ou si le dataset a été régénéré
    # entre-temps (dataset_id différent), on repart de zéro sans lever
    # d'erreur — c'est un cas normal (premier `advance`, ou nouveau dataset
    # produit par `fetch_replay_dataset.py`), pas un état invalide.

    provider.advance()
    set_replay_session(redis_client, context_id, dataset_id=dataset.dataset_id, index=provider.index)
    return _session_out(dataset, provider)


@router.get("/session", response_model=ReplaySessionOut)
def get_session(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context_id = _require_active_replay_context_id(db, user)
    except _NoActiveReplayContext:
        return _no_active_replay_context_error()

    try:
        dataset = load_dataset(_dataset_path())
    except ReplayDatasetError as exc:
        return _dataset_not_found_error(exc)

    session = get_replay_session(redis_client, context_id)
    if session is None or session["dataset_id"] != dataset.dataset_id:
        return api_error_response(
            404,
            ErrorCode.NOT_FOUND,
            "aucune session Replay démarrée pour ce contexte — POST /api/replay/session/reset ou "
            "/api/replay/session/advance d'abord",
        )

    provider = ReplayMarketDataProvider(dataset)
    provider.seek(session["index"])
    return _session_out(dataset, provider)
