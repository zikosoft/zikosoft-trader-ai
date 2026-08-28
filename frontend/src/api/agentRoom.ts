


import { apiGet } from "./client";

export type AgentMessage = {
  id: string;
  agent_type: string;
  conversation_thread_id: string;

  state: string;
  content: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

export type AgentMessagesResponse = {
  messages: AgentMessage[];
};

export type DecisionChainProposal = {
  id: string;
  outcome: string;
  confidence: number | null;
  reasoning_text: string | null;
  risk_flags: unknown[];
  created_at: string;
};

export type DecisionChainCritique = DecisionChainProposal;

export type DecisionChainRiskDecision = {
  id: string;
  outcome: string;
  reasons: unknown[];
  adjustments: Record<string, unknown>;
  created_at: string;
};

export type DecisionChainExplanation = {
  id: string;
  outcome: string;
  novice_summary: string | null;
  expert_summary: string | null;
  created_at: string;
};

export type DecisionChainOrder = {
  id: string;
  side: string;
  status: string;
  quantity: number | null;
  notional: number | null;
  filled_at: string | null;
  submitted_at: string | null;
};

export type DecisionChainResponse = {
  strategy_id: string;
  strategy_name: string | null;
  strategy_type_code: string | null;
  symbol: string;
  market_data_timestamp: string | null;
  // Chaque maillon est honnêtement `null` s'il n'a pas (encore) eu lieu —
  // jamais de 404 pour un état intermédiaire réel (voir docstring backend).
  proposal: DecisionChainProposal | null;
  critique: DecisionChainCritique | null;
  risk_decision: DecisionChainRiskDecision | null;
  explanation: DecisionChainExplanation | null;
  order: DecisionChainOrder | null;
};

export async function fetchAgentMessages(limit = 100): Promise<AgentMessagesResponse> {
  return apiGet<AgentMessagesResponse>(`/api/agents/room/messages?limit=${limit}`);
}

export async function fetchDecisionChain(
  strategyId: string,
  symbol: string,
  marketDataTimestamp: string,
): Promise<DecisionChainResponse> {
  const params = new URLSearchParams({
    strategy_id: strategyId,
    symbol,
    market_data_timestamp: marketDataTimestamp,
  });
  return apiGet<DecisionChainResponse>(`/api/agents/room/decision-chain?${params.toString()}`);
}
