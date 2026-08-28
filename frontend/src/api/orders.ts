

import { apiGet } from "./client";

export type OrderSide = "buy" | "sell";

export type RecentOrder = {
  id: string;
  symbol: string;
  side: OrderSide;
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
