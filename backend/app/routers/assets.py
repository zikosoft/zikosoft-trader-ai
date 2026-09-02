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
from ..alpaca_client import AlpacaClient, AlpacaError
from ..api_errors import api_error_response
from ..auth import get_current_user
from ..db import get_db
from ..models import Asset, ProviderAsset, TradingProvider, User, UserTradingAccount
from ..schemas.assets import (
    AssetCatalogStatusOut,
    AssetSearchItemOut,
    AssetSearchResponse,
    AssetSyncResultOut,
    OptionChainResponse,
    OptionChainSnapshotOut,
    OptionSyncResultOut,
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


@router.post("/options/sync", response_model=OptionSyncResultOut)
def sync_option_assets(
    underlying_symbol: str = Query(..., min_length=1, max_length=10),
    expiration_date_gte: str | None = Query(default=None, max_length=10),
    expiration_date_lte: str | None = Query(default=None, max_length=10),
    option_type: str | None = Query(default=None, pattern="^(call|put)$"),
    strike_price_gte: float | None = Query(default=None, gt=0),
    strike_price_lte: float | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Synchronize one underlying's option contracts without deactivating
    unrelated equities or other option underlyings."""
    account = _alpaca_account(db, user)
    if account is None or not account.encrypted_api_key:
        return api_error_response(
            400,
            ErrorCode.VALIDATION_ERROR,
            "Aucun compte Alpaca connecté — termine d'abord l'onboarding.",
        )
    try:
        result = service.sync_option_contracts(
            db,
            account,
            underlying_symbol=underlying_symbol,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            option_type=option_type,
            strike_price_gte=strike_price_gte,
            strike_price_lte=strike_price_lte,
            limit=limit,
        )
    except service.AssetSyncError as exc:
        return api_error_response(502, ErrorCode.UPSTREAM_ERROR, f"synchronisation des options échouée : {exc}")
    db.commit()
    return OptionSyncResultOut(
        synced_count=result.synced_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        deactivated_count=result.deactivated_count,
        underlying_symbol=result.underlying_symbol,
        synced_at=result.synced_at,
    )


@router.get("/options/chain", response_model=OptionChainResponse)
def option_chain(
    underlying_symbol: str = Query(..., min_length=1, max_length=10),
    expiration_date_gte: str | None = Query(default=None, max_length=10),
    expiration_date_lte: str | None = Query(default=None, max_length=10),
    option_type: str | None = Query(default=None, pattern="^(call|put)$"),
    strike_price_gte: float | None = Query(default=None, gt=0),
    strike_price_lte: float | None = Query(default=None, gt=0),
    feed: str | None = Query(default=None, pattern="^(opra|indicative)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read the latest Alpaca option-chain quotes for contract selection.

    This route deliberately does not write to the catalogue or place an
    order; it is the read-only quote discovery boundary used by the next
    options-trading phase.
    """
    account = _alpaca_account(db, user)
    if account is None or not account.encrypted_api_key:
        return api_error_response(
            400,
            ErrorCode.VALIDATION_ERROR,
            "Aucun compte Alpaca connecté — termine d'abord l'onboarding.",
        )
    from ..encryption import decrypt_secret

    try:
        client = AlpacaClient(
            decrypt_secret(account.encrypted_api_key),
            decrypt_secret(account.encrypted_secret_key),
        )
        snapshots = client.get_option_chain(
            underlying_symbol=underlying_symbol,
            option_type=option_type,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            strike_price_gte=strike_price_gte,
            strike_price_lte=strike_price_lte,
            feed=feed,
            limit=limit,
        )
    except (AlpacaError, ValueError) as exc:
        return api_error_response(502, ErrorCode.UPSTREAM_ERROR, f"lecture de la chaîne options échouée : {exc}")
    return OptionChainResponse(
        underlying_symbol=underlying_symbol.strip().upper(),
        snapshots=[OptionChainSnapshotOut(**snapshot.__dict__) for snapshot in snapshots],
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


@router.get("/options/search", response_model=AssetSearchResponse)
def search_option_assets(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT),
    tradable_only: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search option contracts already synchronized in the catalogue."""
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
        .where(Asset.status == "active", Asset.asset_type == "option", ProviderAsset.status == "active")
    )
    needle = q.strip()
    if needle:
        pattern = f"%{needle}%"
        query = query.where(
            Asset.canonical_symbol.ilike(pattern) | Asset.label.ilike(pattern)
        )
    if tradable_only:
        query = query.where(ProviderAsset.tradable.is_(True))
    rows = db.execute(query.order_by(Asset.canonical_symbol).limit(limit)).all()
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
