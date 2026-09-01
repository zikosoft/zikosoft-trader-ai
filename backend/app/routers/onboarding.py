"""Routes de l'onboarding Alpaca (B07)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.error_log import ErrorModule, log_error

from ..auth import get_current_user
from ..db import engine, get_db
from ..models import PortfolioSnapshot, User, UserTradingAccount
from ..onboarding import get_status, reset_pipeline, run_pipeline
from ..schemas.onboarding import (
    AccountOut,
    BalanceOut,
    ConnectRequest,
    OnboardingStatusResponse,
    StepOut,
)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _latest_balance(db: Session, account: UserTradingAccount) -> BalanceOut | None:
    snapshot = db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.user_id == account.user_id)
        .order_by(PortfolioSnapshot.snapshot_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if snapshot is None:
        return None
    return BalanceOut(
        cash=float(snapshot.cash),
        buying_power=float(snapshot.buying_power),
        portfolio_value=float(snapshot.portfolio_value),
        snapshot_at=snapshot.snapshot_at,
    )


def _status_response(db: Session, account: UserTradingAccount | None, steps) -> OnboardingStatusResponse:
    account_out = None
    if account is not None:
        account_out = AccountOut.model_validate(account)
        account_out.balance = _latest_balance(db, account)
    return OnboardingStatusResponse(
        account=account_out, steps=[StepOut.model_validate(s) for s in steps]
    )


@router.get("/status", response_model=OnboardingStatusResponse)
def status(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> OnboardingStatusResponse:
    account, steps = get_status(db, user)
    return _status_response(db, account, steps)


@router.post("/connect", response_model=OnboardingStatusResponse)
def connect(
    payload: ConnectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OnboardingStatusResponse:
    account = run_pipeline(db, user, api_key=payload.api_key, secret_key=payload.secret_key)
    db.commit()
    if account.status == "failed":
        # Note technique volontairement sans les clés (jamais dans un log,
        # §B07 "aucun secret ... dans les logs") — juste de quoi retrouver
        # l'incident dans le journal B36.
        log_error(
            engine,
            module=ErrorModule.ONBOARDING,
            feature="connect",
            severity="WARNING",
            user_id=user.id,
            response_or_error="onboarding step failed",
            http_status=200,
        )
    _, steps = get_status(db, user)
    return _status_response(db, account, steps)


@router.post("/retry", response_model=OnboardingStatusResponse)
def retry(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> OnboardingStatusResponse:
    """Rejoue le pipeline sans refournir les clés — reprend à la première
    étape non `COMPLETED` (§B07 "Reprendre uniquement l'étape échouée"),
    les clés déjà validées restent chiffrées en base."""
    account = run_pipeline(db, user)
    db.commit()
    _, steps = get_status(db, user)
    return _status_response(db, account, steps)


@router.post("/restart", response_model=OnboardingStatusResponse)
def restart(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> OnboardingStatusResponse:
    """§B07 "Restart complete setup" — remet tout à `PENDING`, efface les
    identifiants stockés. Un nouveau `POST /connect` avec de nouvelles clés
    est nécessaire ensuite."""
    reset_pipeline(db, user)
    db.commit()
    account, steps = get_status(db, user)
    return _status_response(db, account, steps)
