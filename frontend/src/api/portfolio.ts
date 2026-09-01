// Client API pour le portefeuille (`GET /api/portfolio/*`, B18 backend —
// volontairement resté backend-only à l'époque, voir docstring de
// `backend/app/routers/portfolio.py` : "B26 consommera ces routes"). Ce
// module frontend n'existait pas avant B26 : premier consommateur réel de
// ces routes.

import { apiGet } from "./client";

export type PortfolioSummary = {
  cash: number;
  buying_power: number;
  portfolio_value: number;
  // `null` tant que le worker n'a pas encore assez de tours — jamais
  // fabriqué en 0 (voir backend/app/schemas/portfolio.py).
  daily_pl: number | null;
  total_pl: number | null;
  snapshot_at: string;
};

export type Position = {
  symbol: string;
  quantity: number;
  average_entry_price: number | null;
  market_value: number | null;
  unrealized_pl: number | null;
  snapshot_at: string;
};

export type PositionsResponse = {
  positions: Position[];
  snapshot_at: string | null;
};

export type PerformanceCard = {
  window: "1D" | "3D" | "7D";
  available: boolean;
  reason?: string | null;
  value_change?: number | null;
  percent_change?: number | null;
};

export type PerformanceCardsResponse = {
  cards: PerformanceCard[];
};

export type PortfolioHistoryItem = {
  cash: number;
  buying_power: number;
  portfolio_value: number;
  daily_pl: number | null;
  total_pl: number | null;
  snapshot_at: string;
};

export type PortfolioHistoryResponse = {
  items: PortfolioHistoryItem[];
  total: number;
  limit: number;
  offset: number;
};

export async function fetchPortfolioSummary(): Promise<PortfolioSummary> {
  return apiGet<PortfolioSummary>("/api/portfolio/summary");
}

export async function fetchPositions(): Promise<PositionsResponse> {
  return apiGet<PositionsResponse>("/api/portfolio/positions");
}

export async function fetchPerformanceCards(): Promise<PerformanceCardsResponse> {
  return apiGet<PerformanceCardsResponse>("/api/portfolio/performance");
}

// §B27 "Courbe portefeuille"/"Sparklines 1D-7D" — premier consommateur
// frontend de `GET /api/portfolio/history` (B18, backend-only jusqu'ici).
export async function fetchPortfolioHistory(limit = 200): Promise<PortfolioHistoryResponse> {
  return apiGet<PortfolioHistoryResponse>(`/api/portfolio/history?limit=${limit}`);
}
