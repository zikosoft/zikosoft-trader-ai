import { useCallback, useMemo, useState, type ReactNode } from "react";
import {
  AgentRoomContext,
  type AgentRoomContextValue,
  type AgentRoomMode,
  type AgentRoomTab,
  type DecisionWindowKey,
} from "./agentRoomContextObject";

// §B28 "Agent Room" (décision D074, voir AVANCEMENT.md) : même pattern que
// `ThemeModeContext.tsx` (D060, React Context + hooks natifs) — état
// transverse à l'app, petit, peu fréquemment modifié. Seul le MODE
// d'affichage (compact/docked/fullscreen) est mémorisé dans `localStorage`
// (§checklist "préférence sauvegardée") ; `open`/`activeTab`/`selectedWindow`
// repartent volontairement de zéro à chaque session — l'Agent Room ne doit
// jamais s'imposer au chargement de l'app (§D010/D011 "ne pas bloquer le
// dashboard"), un panneau resté ouvert la dernière fois ne doit pas se
// rouvrir tout seul au prochain login.

const STORAGE_KEY = "zikosofttrader.agent-room-mode";

function readInitialMode(): AgentRoomMode {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "compact" || stored === "docked" || stored === "fullscreen") return stored;
  } catch {
    // localStorage indisponible (navigation privée stricte, etc.) — repli
    // silencieux sur le mode par défaut ci-dessous.
  }
  return "compact";
}

export function AgentRoomProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<AgentRoomMode>(readInitialMode);
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<AgentRoomTab>("live");
  const [selectedWindow, setSelectedWindow] = useState<DecisionWindowKey | null>(null);

  const setMode = useCallback((next: AgentRoomMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Rien à faire — le mode reste actif pour cette session d'onglet,
      // simplement pas mémorisé pour la prochaine visite.
    }
  }, []);

  const openRoom = useCallback(
    (nextMode?: AgentRoomMode) => {
      if (nextMode) setMode(nextMode);
      setOpen(true);
    },
    [setMode],
  );

  const closeRoom = useCallback(() => setOpen(false), []);

  const selectDecision = useCallback((key: DecisionWindowKey) => {
    setSelectedWindow(key);
    setActiveTab("decision");
  }, []);

  const value = useMemo<AgentRoomContextValue>(
    () => ({
      mode,
      open,
      activeTab,
      selectedWindow,
      setMode,
      openRoom,
      closeRoom,
      setActiveTab,
      selectDecision,
    }),
    [mode, open, activeTab, selectedWindow, setMode, openRoom, closeRoom, selectDecision],
  );

  return <AgentRoomContext.Provider value={value}>{children}</AgentRoomContext.Provider>;
}
