// Client API pour "Résumé Agent Room" et "Risque" (`GET
// /api/agents/decisions/recent`, `GET /api/risk/decisions/recent`, B26).
// Portée volontairement minimale — voir
// `backend/app/routers/agent_activity.py` : ce n'est pas l'Agent Room
// complet (Live Debate/Decision Details restent des placeholders honnêtes
// depuis B25, propriété de B28/B29), juste deux petits widgets de synthèse.

import { apiGet } from "./client";

export type AgentDecision = {
  id: string;
  strategy_id: string | null;
  agent_type: string;
  decision_type: string;
  outcome: string;
  confidence: number | null;
  created_at: string;
};

export type RecentAgentDecisionsResponse = {
  decisions: AgentDecision[];
};

export type RiskDecision = {
  id: string;
  agent_decision_id: string;
  outcome: string;
  reasons: unknown[];
  created_at: string;
};

export type RecentRiskDecisionsResponse = {
  decisions: RiskDecision[];
};

export async function fetchRecentAgentDecisions(limit = 5): Promise<RecentAgentDecisionsResponse> {
  return apiGet<RecentAgentDecisionsResponse>(`/api/agents/decisions/recent?limit=${limit}`);
}

export async function fetchRecentRiskDecisions(limit = 5): Promise<RecentRiskDecisionsResponse> {
  return apiGet<RecentRiskDecisionsResponse>(`/api/risk/decisions/recent?limit=${limit}`);
}
