"""Schémas Pydantic — B09 (catalogue des actifs Alpaca).

Trois routes, trois formes de sortie : `POST /sync` renvoie un résumé
d'exécution (compteurs), `GET /search` renvoie une page du catalogue
(pour l'autocomplete symbole), `GET /status` renvoie l'état de fraîcheur
du catalogue (§checklist "Afficher dernière synchronisation")."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AssetSyncResultOut(BaseModel):
    synced_count: int
    created_count: int
    updated_count: int
    deactivated_count: int
    synced_at: datetime


class OptionSyncResultOut(BaseModel):
    synced_count: int
    created_count: int
    updated_count: int
    deactivated_count: int
    underlying_symbol: str
    synced_at: datetime


class OptionChainSnapshotOut(BaseModel):
    symbol: str
    bid_price: float | None
    ask_price: float | None
    last_trade_price: float | None
    bid_size: int | None
    ask_size: int | None
    implied_volatility: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None


class OptionChainResponse(BaseModel):
    underlying_symbol: str
    snapshots: list[OptionChainSnapshotOut]


class AssetSearchItemOut(BaseModel):
    canonical_symbol: str
    label: str
    asset_type: str
    tradable: bool
    fractionable: bool
    shortable: bool


class AssetSearchResponse(BaseModel):
    items: list[AssetSearchItemOut]


class AssetCatalogStatusOut(BaseModel):
    last_synced_at: datetime | None
    active_asset_count: int
