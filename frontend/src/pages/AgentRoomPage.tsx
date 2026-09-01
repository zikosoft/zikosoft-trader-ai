import { useEffect } from "react";
import { useAgentRoom } from "../useAgentRoom";

// §B28 — le panneau Agent Room réel est un overlay GLOBAL rendu par
// `AppShell.tsx` (D010/D011 : trois modes, ne pas bloquer le dashboard),
// pas une page routée classique. Cette page reste l'ancrage `/agent-room`
// (accès direct par URL, lien profond) : elle se contente d'ouvrir le
// panneau en plein écran au montage, puis ne rend rien elle-même — le
// contenu réel vient de `AgentRoomPanel` monté par `AppShell`.
export default function AgentRoomPage() {
  const { openRoom } = useAgentRoom();

  useEffect(() => {
    openRoom("fullscreen");
    // Ouverture une seule fois, à l'arrivée sur cette route — un
    // changement ultérieur de mode/état ne doit pas re-déclencher l'effet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
