"""Catalogue des actifs Alpaca (B09) — synchronise `assets`/`provider_assets`
(schéma posé dès B03, jamais alimenté jusqu'ici) depuis `GET /v2/assets`
(`AlpacaClient.get_assets`, ajouté pour cette brique).

Mapping symbole canonique <-> symbole provider (§9.3 de la spec) :
`Asset.canonical_symbol` EST le symbole Alpaca en V1 (single-provider —
aucune divergence à résoudre tant qu'un deuxième provider n'existe pas),
mais les deux tables restent séparées dès aujourd'hui pour ne pas avoir à
migrer si un jour Alpaca et un futur provider utilisaient des conventions
de symbole différentes pour le même actif sous-jacent.

**Actualiser sans supprimer l'historique (§checklist B09) :** un re-sync
ne supprime JAMAIS de ligne — `Asset`/`ProviderAsset` déjà connus sont mis
à jour (upsert), les nouveaux sont créés ; un actif renvoyé par Alpaca lors
d'un sync précédent mais absent du sync courant voit son
`ProviderAsset.status` basculer à `"inactive"` plutôt que d'être
supprimé — un ordre déjà passé sur ce symbole reste référencable."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .alpaca_client import AlpacaAsset, AlpacaClient, AlpacaError
from .models import Asset, ProviderAsset, TradingProvider, UserTradingAccount

# §B09 "type : equity, ETF, crypto, option" — mapping depuis `asset_class`
# Alpaca (`us_equity`/`crypto` en pratique ; `etf`/`option` ne sont pas
# distingués par `asset_class` côté Alpaca — un ETF est un `us_equity` du
# point de vue de cet endpoint, aucune information supplémentaire n'est
# renvoyée par `GET /v2/assets` pour le distinguer d'une action ordinaire.
# Repli honnête sur `"equity"` plutôt que deviner depuis le nom.
_ASSET_CLASS_MAP: dict[str, str] = {
    "us_equity": "equity",
    "crypto": "crypto",
}


class AssetSyncError(Exception):
    """Enveloppe toute erreur Alpaca (`AlpacaError`) rencontrée pendant un
    sync — permet à l'appelant (onboarding, route manuelle) de choisir sa
    propre gestion sans importer `alpaca_client` directement."""


@dataclass(frozen=True)
class AssetSyncResult:
    synced_count: int
    created_count: int
    updated_count: int
    deactivated_count: int
    synced_at: datetime


def _get_alpaca_provider(db: Session) -> TradingProvider:
    return db.execute(select(TradingProvider).where(TradingProvider.code == "alpaca")).scalar_one()


def _asset_type_for(alpaca_asset: AlpacaAsset) -> str:
    return _ASSET_CLASS_MAP.get(alpaca_asset.asset_class, "equity")


def sync_assets(
    db: Session,
    account: UserTradingAccount,
    *,
    client_factory: type[AlpacaClient] = AlpacaClient,
    status: str = "active",
    asset_class: str = "us_equity",
) -> AssetSyncResult:
    """Point d'entrée unique — utilisé à la fois par l'étape d'onboarding
    `assets_synchronized` (avec le compte tout juste connecté) et par la
    route manuelle `POST /api/assets/sync` (avec un compte déjà connecté).
    `account` doit déjà porter des clés déchiffrables (§B07) — cette
    fonction ne valide PAS les identifiants elle-même, contrairement à
    l'étape `credentials_validated` qui l'a déjà fait avant."""
    from .encryption import decrypt_secret  # import tardif — évite un cycle avec onboarding.py

    client = client_factory(
        decrypt_secret(account.encrypted_api_key), decrypt_secret(account.encrypted_secret_key)
    )
    try:
        alpaca_assets = client.get_assets(status=status, asset_class=asset_class)
    except AlpacaError as exc:
        raise AssetSyncError(str(exc)) from exc

    provider = _get_alpaca_provider(db)
    now = datetime.now(UTC)

    # Index des `ProviderAsset` déjà connus pour ce provider — une seule
    # requête plutôt qu'une par actif (le catalogue Alpaca peut compter
    # plusieurs milliers de lignes pour `us_equity`).
    existing_provider_assets = {
        row.provider_symbol: row
        for row in db.execute(
            select(ProviderAsset).where(ProviderAsset.provider_id == provider.id)
        ).scalars()
    }
    existing_assets = {row.canonical_symbol: row for row in db.execute(select(Asset)).scalars()}

    seen_symbols: set[str] = set()
    created_count = 0
    updated_count = 0

    for alpaca_asset in alpaca_assets:
        seen_symbols.add(alpaca_asset.symbol)

        asset = existing_assets.get(alpaca_asset.symbol)
        if asset is None:
            asset = Asset(
                canonical_symbol=alpaca_asset.symbol,
                label=alpaca_asset.name,
                asset_type=_asset_type_for(alpaca_asset),
                currency="USD",
                status="active",
            )
            db.add(asset)
            db.flush()
            existing_assets[alpaca_asset.symbol] = asset
        else:
            asset.label = alpaca_asset.name
            asset.asset_type = _asset_type_for(alpaca_asset)
            asset.status = "active"

        provider_asset = existing_provider_assets.get(alpaca_asset.symbol)
        if provider_asset is None:
            provider_asset = ProviderAsset(
                id=uuid.uuid4(),
                asset_id=asset.id,
                provider_id=provider.id,
                provider_asset_id=alpaca_asset.id,
                provider_symbol=alpaca_asset.symbol,
                tradable=alpaca_asset.tradable,
                fractionable=alpaca_asset.fractionable,
                shortable=alpaca_asset.shortable,
                status="active",
                metadata_json={"exchange": alpaca_asset.exchange, "asset_class": alpaca_asset.asset_class},
                last_synced_at=now,
            )
            db.add(provider_asset)
            existing_provider_assets[alpaca_asset.symbol] = provider_asset
            created_count += 1
        else:
            provider_asset.asset_id = asset.id
            provider_asset.provider_asset_id = alpaca_asset.id
            provider_asset.tradable = alpaca_asset.tradable
            provider_asset.fractionable = alpaca_asset.fractionable
            provider_asset.shortable = alpaca_asset.shortable
            provider_asset.status = "active"
            provider_asset.metadata_json = {
                "exchange": alpaca_asset.exchange,
                "asset_class": alpaca_asset.asset_class,
            }
            provider_asset.last_synced_at = now
            updated_count += 1

    # §"Actualiser sans supprimer l'historique" — jamais un DELETE : un
    # `ProviderAsset` actif avant ce sync mais absent du résultat courant
    # (retiré du catalogue Alpaca, ou simplement hors du filtre
    # `status`/`asset_class` demandé) bascule à `"inactive"`, il reste
    # référencable par tout ordre historique qui le cite déjà.
    deactivated_count = 0
    for symbol, provider_asset in existing_provider_assets.items():
        if symbol not in seen_symbols and provider_asset.status != "inactive":
            provider_asset.status = "inactive"
            deactivated_count += 1

    account.metadata_json = {**account.metadata_json, "assets_last_synced_at": now.isoformat()}
    db.flush()

    return AssetSyncResult(
        synced_count=len(alpaca_assets),
        created_count=created_count,
        updated_count=updated_count,
        deactivated_count=deactivated_count,
        synced_at=now,
    )


def last_sync_status(db: Session, account: UserTradingAccount | None) -> tuple[datetime | None, int]:
    """§checklist "Afficher dernière synchronisation" — lit la date écrite
    par `sync_assets` ci-dessus sur `account.metadata_json` (pas de nouvelle
    colonne : `UserTradingAccount.metadata_json` existe déjà, réutilisé
    exactement comme `account_synchronized` le fait pour `alpaca_status`)
    et le compte total d'actifs actifs (catalogue partagé, pas par
    utilisateur)."""
    synced_at: datetime | None = None
    if account is not None:
        raw = (account.metadata_json or {}).get("assets_last_synced_at")
        if raw:
            synced_at = datetime.fromisoformat(raw)
    count = db.execute(
        select(ProviderAsset).where(ProviderAsset.status == "active")
    ).scalars()
    total = sum(1 for _ in count)
    return synced_at, total
