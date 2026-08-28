

import { apiGet } from "./client";

export type ServiceCheckStatus = "HEALTHY" | "DEGRADED" | "DISCONNECTED" | "STARTING";

export type ServiceCheck = {
  status: ServiceCheckStatus;
  latency_ms?: number;
  error?: string;
  last_heartbeat_at?: string | null;
};

export type KillSwitchDetail = {
  actor_user_id: string | null;
  reason: string | null;
  occurred_at: string | null;
};

export type SystemHealth = {
  status: string;
  checks: Record<string, ServiceCheck>;

  trading_kill_switch_engaged: boolean | null;

  trading_kill_switch_detail: KillSwitchDetail | null;
};


export const SERVICE_LABELS: Record<string, string> = {
  "backend-api": "API backend",
  postgres: "Base de données (PostgreSQL)",
  redis: "Bus d'événements (Redis)",
  "market-agent": "Market Agent",
  "strategy-agent": "Strategy Agent",
  "risk-critic-agent": "Risk Critic Agent",
  "execution-explanation-agent": "Execution & Explanation Agent",
  "risk-engine": "Risk Engine",
  "order-worker": "Order Worker",
};

// Route publique (aucune authentification requise, voir backend/app/main.py
// — même route utilisable avant login, un incident système concerne tout
// le monde, pas seulement un utilisateur connecté).
export async function fetchSystemHealth(): Promise<SystemHealth> {
  return apiGet<SystemHealth>("/api/system/health");
}
