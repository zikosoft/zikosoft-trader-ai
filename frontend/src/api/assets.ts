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
