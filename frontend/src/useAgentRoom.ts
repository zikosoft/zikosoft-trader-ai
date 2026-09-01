import { useContext } from "react";
import { AgentRoomContext, type AgentRoomContextValue } from "./agentRoomContextObject";

// Séparé de `AgentRoomContext.tsx` (§lint react-refresh/only-export-components)
// — même raison que `useThemeMode.ts`.
export function useAgentRoom(): AgentRoomContextValue {
  const ctx = useContext(AgentRoomContext);
  if (!ctx) throw new Error("useAgentRoom doit être utilisé sous AgentRoomProvider");
  return ctx;
}
