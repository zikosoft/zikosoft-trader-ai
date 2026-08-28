


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
