// Client API pour "Ordres récents" (`GET /api/orders/recent`, B26).
// Portée volontairement minimale — voir `backend/app/routers/orders.py` :
// ce n'est pas l'écran Orders complet (toujours un placeholder honnête
// depuis B25, "backend prêt B17 UI à venir"), juste le widget dashboard.

import { apiGet } from "./client";
import type { OptionInstrument } from "./options";

export type OrderSide = "buy" | "sell";

export type RecentOrder = {
  id: string;
  symbol: string;
  side: OrderSide;
  asset_class: string;
  option_instrument: OptionInstrument | null;
  quantity: number | null;
  notional: number | null;
  order_type: string;
  status: string;
  submitted_at: string | null;
  filled_at: string | null;
  created_at: string;
};

export type RecentOrdersResponse = {
  orders: RecentOrder[];
};

export async function fetchRecentOrders(limit = 10): Promise<RecentOrdersResponse> {
  return apiGet<RecentOrdersResponse>(`/api/orders/recent?limit=${limit}`);
}
