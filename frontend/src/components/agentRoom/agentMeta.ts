import { AGENT_COLORS } from "../../theme";

// §B28 "Live Debate" — libellé humain + initiale d'avatar par `agent_type`
// (colonne réelle de `agent_messages`). Les QUATRE clés sont les seules
// valeurs réellement écrites par le pipeline (voir `theme.ts::AGENT_COLORS`)
// — un `agent_type` inconnu retombe honnêtement sur la valeur brute plutôt
// que de fabriquer un libellé.

export const AGENT_LABELS: Record<string, string> = {
  strategy_agent: "Strategy Agent",
  risk_critic_agent: "Risk Critic Agent",
  risk_engine: "Risk Engine",
  execution_explanation_agent: "Execution & Explanation Agent",
};

export function agentLabel(agentType: string): string {
  return AGENT_LABELS[agentType] ?? agentType;
}

export function agentColor(agentType: string): string {
  return AGENT_COLORS[agentType] ?? "#5c6370";
}

export function agentInitials(agentType: string): string {
  const label = agentLabel(agentType);
  const words = label.split(/[\s&]+/).filter(Boolean);
  return words
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

// §D073 — les QUATRE états possibles du modèle `AgentMessage`. `completed`/
// `rejected` sont les seuls réellement produits par ce pipeline synchrone à
// repli déterministe garanti ; `thinking`/`failed` sont documentés
// honnêtement (jamais masqués) même si jamais exercés aujourd'hui — voir
// AVANCEMENT.md.
export const STATE_META: Record<string, { label: string; color: "success" | "error" | "info" | "warning" | "default" }> = {
  completed: { label: "Complété", color: "success" },
  rejected: { label: "Rejeté", color: "error" },
  thinking: { label: "En réflexion…", color: "info" },
  failed: { label: "Échec", color: "warning" },
};

export function stateMeta(state: string): { label: string; color: "success" | "error" | "info" | "warning" | "default" } {
  return STATE_META[state] ?? { label: state, color: "default" };
}
