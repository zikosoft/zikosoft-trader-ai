import { createContext } from "react";

// Objet React Context brut, séparé de `AgentRoomContext.tsx` (le composant
// `AgentRoomProvider`) et de `useAgentRoom.ts` (le hook) — même séparation
// que `themeModeContextObject.ts`/`ThemeModeContext.tsx`/`useThemeMode.ts`
// (§lint react-refresh/only-export-components : un fichier qui exporte un
// composant doit n'exporter QUE des composants).

// §D010/D011 : "Agent Room en trois modes | Ne pas bloquer le
// dashboard | Compact/docked/full-screen" — trois modes d'affichage, jamais
// une simple page routée qui remplacerait le reste de l'app.
export type AgentRoomMode = "compact" | "docked" | "fullscreen";

export type AgentRoomTab = "live" | "ask" | "decision";

// Clé de fenêtre de décision (§B28 "Decision Details") — voir
// `backend/app/agent_room.py` : `(strategy_id, symbol,
// market_data_timestamp)`, PAS `correlation_id` (partageable entre
// stratégies concurrentes sur le même tick, voir D073).
export type DecisionWindowKey = {
  strategyId: string;
  symbol: string;
  marketDataTimestamp: string;
};

export type AgentRoomContextValue = {
  mode: AgentRoomMode;
  open: boolean;
  activeTab: AgentRoomTab;
  selectedWindow: DecisionWindowKey | null;
  setMode: (mode: AgentRoomMode) => void;
  openRoom: (mode?: AgentRoomMode) => void;
  closeRoom: () => void;
  setActiveTab: (tab: AgentRoomTab) => void;
  // Bascule sur l'onglet Decision Details ET mémorise la fenêtre — c'est LE
  // mécanisme unique de "lien stratégie/risque/ordre" (§checklist B28) :
  // cliquer un message du Live Debate ouvre sa chaîne de décision complète.
  selectDecision: (key: DecisionWindowKey) => void;
};

export const AgentRoomContext = createContext<AgentRoomContextValue | null>(null);
