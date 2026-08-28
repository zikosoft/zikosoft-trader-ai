
import { apiGet } from "./client";

export type Bar = {
  bar_at: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  volume: number | null;
};

export type BarsResponse = {
  symbol: string;
  timeframe: string;
  bars: Bar[];
};

export type Quote = {
  symbol: string;
  price: number;
  as_of: string | null;
  updated_at: string;
};

export type OrderMarker = {
  id: string;
  side: string;
  status: string;
  quantity: number | null;
  notional: number | null;
  filled_at: string | null;
  submitted_at: string | null;
  filled_price: number | null;
  stop_loss: Record<string, unknown> | null;
  take_profit: Record<string, unknown> | null;
};

export type OrderMarkersResponse = {
  symbol: string;
  orders: OrderMarker[];
};

export type ProposalMarker = {
  id: string;
  strategy_id: string | null;
  outcome: string;
  confidence: number | null;
  market_data_timestamp: string | null;
  reasoning_text: string | null;
  created_at: string;
};

export type RiskEventMarker = {
  id: string;
  agent_decision_id: string;
  outcome: string;
  reasons: unknown[];
  market_data_timestamp: string | null;
  created_at: string;
};

export type DecisionMarkersResponse = {
  symbol: string;
  proposals: ProposalMarker[];
  risk_events: RiskEventMarker[];
};

export type StrategyActivity = {
  strategy_id: string;
  type_code: string;
  name: string;
  status: string;
  order_count: number;
  buy_count: number;
  sell_count: number;
  total_notional: number;
};

export type StrategyActivityResponse = {
  strategies: StrategyActivity[];
};

export async function fetchSymbols(): Promise<string[]> {
  const res = await apiGet<{ symbols: string[] }>("/api/market/symbols");
  return res.symbols;
}

export async function fetchBars(symbol: string, timeframe = "1Day", limit = 200): Promise<BarsResponse> {
  const params = new URLSearchParams({ symbol, timeframe, limit: String(limit) });
  return apiGet<BarsResponse>(`/api/market/bars?${params.toString()}`);
}

export async function fetchQuote(symbol: string): Promise<Quote> {
  const params = new URLSearchParams({ symbol });
  return apiGet<Quote>(`/api/market/quote?${params.toString()}`);
}

export async function fetchOrderMarkers(symbol: string, limit = 100): Promise<OrderMarkersResponse> {
  const params = new URLSearchParams({ symbol, limit: String(limit) });
  return apiGet<OrderMarkersResponse>(`/api/market/orders?${params.toString()}`);
}

export async function fetchDecisionMarkers(symbol: string, limit = 50): Promise<DecisionMarkersResponse> {
  const params = new URLSearchParams({ symbol, limit: String(limit) });
  return apiGet<DecisionMarkersResponse>(`/api/market/decisions?${params.toString()}`);
}

export async function fetchStrategyActivity(): Promise<StrategyActivityResponse> {
  return apiGet<StrategyActivityResponse>("/api/market/strategy-activity");
}
