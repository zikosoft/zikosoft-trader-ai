// Client API pour les notifications in-app (§B20, `backend/app/routers/alerts.py`).
// Scopé au contexte d'exécution actif côté backend — pas de paramètre de
// contexte ici, même principe que `orders.ts`/`portfolio.ts`.

import { apiGet, apiPost } from "./client";

export type AlertSeverity = "INFO" | "WARNING" | "CRITICAL";

export type AlertItem = {
  id: string;
  category: string;
  severity: AlertSeverity;
  title: string;
  message: string;
  related_entity_type: string | null;
  related_entity_id: string | null;
  is_read: boolean;
  created_at: string;
};

export type AlertListResponse = {
  alerts: AlertItem[];
  total: number;
};

export type UnreadCountResponse = {
  unread_count: number;
};

export type MarkReadResponse = {
  updated_count: number;
};

export async function fetchAlerts(
  { unreadOnly = false, limit = 20, offset = 0 }: { unreadOnly?: boolean; limit?: number; offset?: number } = {},
): Promise<AlertListResponse> {
  const params = new URLSearchParams({
    unread_only: String(unreadOnly),
    limit: String(limit),
    offset: String(offset),
  });
  return apiGet<AlertListResponse>(`/api/alerts?${params.toString()}`);
}

export async function fetchUnreadAlertCount(): Promise<UnreadCountResponse> {
  return apiGet<UnreadCountResponse>("/api/alerts/unread-count");
}

export async function markAlertRead(alertId: string): Promise<MarkReadResponse> {
  return apiPost<MarkReadResponse>(`/api/alerts/${alertId}/read`);
}

export async function markAllAlertsRead(): Promise<MarkReadResponse> {
  return apiPost<MarkReadResponse>("/api/alerts/read-all");
}
