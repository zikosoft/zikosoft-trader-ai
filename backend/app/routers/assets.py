"""Routes du catalogue des actifs Alpaca (B09).

`POST /sync` déclenche un sync manuel (le sync initial a déjà lieu pendant
l'onboarding, étape `assets_synchronized` — voir `onboarding.py`) ; utile
pour rafraîchir le catalogue sans repasser par tout le pipeline. `GET
/search` alimente l'autocomplete symbole du frontend (création de
stratégie, B12). `GET /status` alimente la carte Settings (dernière sync,
nombre d'actifs)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.errors import ErrorCode

from .. import assets as service
from ..api_errors import api_error_response
from ..auth import get_current_user
from ..db import get_db
from ..models import Asset, ProviderAsset, TradingProvider, User, UserTradingAccount
from ..schemas.assets import (
    AssetCatalogStatusOut,
    AssetSearchItemOut,
    AssetSearchResponse,
    AssetSyncResultOut,
)

router = APIRouter(prefix="/api/assets", tags=["assets"])

MAX_SEARCH_LIMIT = 25
DEFAULT_SEARCH_LIMIT = 10


def _alpaca_account(db: Session, user: User) -> UserTradingAccount | None:
    provider = db.execute(
        select(TradingProvider).where(TradingProvider.code == "alpaca")
    ).scalar_one()
    return db.execute(
        select(UserTradingAccount).where(
            UserTradingAccount.user_id == user.id,
            UserTradingAccount.trading_provider_id == provider.id,
        )
    ).scalar_one_or_none()


@router.post("/sync", response_model=AssetSyncResultOut)
def sync_assets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = _alpaca_account(db, user)
    if account is None or not account.encrypted_api_key:
        return api_error_response(
            400,
            ErrorCode.VALIDATION_ERROR,
            "Aucun compte Alpaca connecté — termine d'abord l'onboarding.",
        )
    try:
        result = service.sync_assets(db, account)
    except service.AssetSyncError as exc:
        return api_error_response(502, ErrorCode.UPSTREAM_ERROR, f"synchronisation du catalogue échouée : {exc}")
    db.commit()
    return AssetSyncResultOut(
        synced_count=result.synced_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        deactivated_count=result.deactivated_count,
        synced_at=result.synced_at,
    )


@router.get("/search", response_model=AssetSearchResponse)
def search_assets(
    q: str = Query(default="", max_length=50),
    limit: int = Query(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT),
    tradable_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Catalogue partagé (pas de scoping par utilisateur/contexte — §9.3, à
    # la différence des ordres/positions) : `user` n'est là que pour exiger
    # l'authentification, cohérent avec le reste de l'API (§B05).
    del user
    query = (
        select(
            Asset.canonical_symbol,
            Asset.label,
            Asset.asset_type,
            ProviderAsset.tradable,
            ProviderAsset.fractionable,
            ProviderAsset.shortable,
        )
        .join(ProviderAsset, ProviderAsset.asset_id == Asset.id)
        .where(Asset.status == "active", ProviderAsset.status == "active")
    )
    needle = q.strip()
    if needle:
        pattern = f"%{needle}%"
        query = query.where(
            Asset.canonical_symbol.ilike(pattern) | Asset.label.ilike(pattern)
        )
    if tradable_only:
        query = query.where(ProviderAsset.tradable.is_(True))
    query = query.order_by(Asset.canonical_symbol).limit(limit)

    rows = db.execute(query).all()
    return AssetSearchResponse(
        items=[
            AssetSearchItemOut(
                canonical_symbol=row.canonical_symbol,
                label=row.label,
                asset_type=row.asset_type,
                tradable=row.tradable,
                fractionable=row.fractionable,
                shortable=row.shortable,
            )
            for row in rows
        ]
    )


@router.get("/status", response_model=AssetCatalogStatusOut)
def catalog_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = _alpaca_account(db, user)
    synced_at, total = service.last_sync_status(db, account)
    return AssetCatalogStatusOut(last_synced_at=synced_at, active_asset_count=total)
