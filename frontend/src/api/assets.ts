// Client API pour le catalogue des actifs Alpaca (§B09,
// `backend/app/routers/assets.py`). Catalogue partagé — pas de scoping par
// contexte d'exécution, à la différence de `orders.ts`/`portfolio.ts`.

import { apiGet, apiPost } from "./client";

export type AssetSearchItem = {
  canonical_symbol: string;
  label: string;
  asset_type: string;
  tradable: boolean;
  fractionable: boolean;
  shortable: boolean;
};

export type AssetSearchResponse = {
  items: AssetSearchItem[];
};

export type AssetSyncResult = {
  synced_count: number;
  created_count: number;
  updated_count: number;
  deactivated_count: number;
  synced_at: string;
};

export type AssetCatalogStatus = {
  last_synced_at: string | null;
  active_asset_count: number;
};

/** Read-only option-chain quote returned by Alpaca for one OCC contract. */
export type OptionChainSnapshot = {
  symbol: string;
  bid_price: number | null;
  ask_price: number | null;
  last_trade_price: number | null;
  bid_size: number | null;
  ask_size: number | null;
  implied_volatility: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
};

export type OptionChainResponse = {
  underlying_symbol: string;
  snapshots: OptionChainSnapshot[];
};

export type OptionSyncResult = AssetSyncResult & {
  underlying_symbol: string;
};

export async function searchAssets(
  q: string,
  { limit = 10, tradableOnly = true }: { limit?: number; tradableOnly?: boolean } = {},
): Promise<AssetSearchResponse> {
  const params = new URLSearchParams({
    q,
    limit: String(limit),
    tradable_only: String(tradableOnly),
  });
  return apiGet<AssetSearchResponse>(`/api/assets/search?${params.toString()}`);
}

export async function fetchAssetCatalogStatus(): Promise<AssetCatalogStatus> {
  return apiGet<AssetCatalogStatus>("/api/assets/status");
}

export async function syncAssetCatalog(): Promise<AssetSyncResult> {
  return apiPost<AssetSyncResult>("/api/assets/sync");
}

function optionUnderlyingQuery(underlyingSymbol: string): string {
  return new URLSearchParams({ underlying_symbol: underlyingSymbol.trim().toUpperCase() }).toString();
}

/**
 * Imports the contracts available for one underlying into the local catalog.
 * This endpoint only discovers contracts; it never places an order.
 */
export async function syncOptionContracts(underlyingSymbol: string): Promise<OptionSyncResult> {
  return apiPost<OptionSyncResult>(`/api/assets/options/sync?${optionUnderlyingQuery(underlyingSymbol)}`);
}

/** Reads the current Alpaca option-chain quotes without changing the catalog. */
export async function fetchOptionChain(underlyingSymbol: string): Promise<OptionChainResponse> {
  return apiGet<OptionChainResponse>(`/api/assets/options/chain?${optionUnderlyingQuery(underlyingSymbol)}`);
}
