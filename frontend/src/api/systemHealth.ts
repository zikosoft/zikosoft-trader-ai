// Client API pour la santé système agrégée (B22 backend, B23 UX incident).
//
// §B25 : importe désormais `apiGet` depuis `api/client.ts` (client API
// centralisé) au lieu de `parseOrThrow` depuis `api/auth.ts` — changement
// d'import uniquement, comportement strictement identique (même requête,
// même gestion d'erreur). `SERVICE_LABELS` déménage aussi ici depuis
// `IncidentBanner.tsx` (B23) : la nouvelle page System Health (B25) et le
// bandeau d'incident (B23) doivent afficher le MÊME libellé humain pour
// chaque service — un unique point de définition, comme
// `shared/shared/watchdog.py::ESSENTIAL_SERVICES` (D052-055, backend) évite
// déjà la même divergence entre le Watchdog et `backend/app/main.py`.

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
  // §B26 "Kill switch" — état RÉEL déjà appliqué par le Risk Engine (B15),
  // exposé en lecture seule ici (aucun bouton). `null` si Redis était
  // injoignable au moment de la lecture (backend/app/main.py) — distinct
  // de `false`, jamais fabriqué comme "trading actif" par défaut.
  trading_kill_switch_engaged: boolean | null;
  // §B31 — qui/quand/pourquoi du dernier engagement, `null` tant que
  // `trading_kill_switch_engaged` n'est pas `true` (voir backend/app/main.py).
  trading_kill_switch_detail: KillSwitchDetail | null;
};

// Même 9 services essentiels que `shared/shared/watchdog.py::ESSENTIAL_SERVICES`
// (B22) — dupliqué ici en constante plutôt que généré dynamiquement : le
// frontend n'a aucun moyen d'importer une constante Python, et cette liste
// ne change qu'au rythme des bricks structurantes du projet (jamais à
// l'exécution).
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
