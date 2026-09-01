import ForumIcon from "@mui/icons-material/Forum";
import { Fab, Paper, Tooltip } from "@mui/material";
import { useAgentRoom } from "../../useAgentRoom";
import AgentRoomPanel from "./AgentRoomPanel";

// §B28 checklist "boutons toujours accessibles" — point d'entrée flottant,
// AU-DESSUS de tout le reste de l'app (D010/D011 "ne pas bloquer le
// dashboard") :
// - Panneau fermé (n'importe quel mode) : un simple bouton flottant pour
//   rouvrir l'Agent Room dans son dernier mode utilisé.
// - Panneau ouvert EN MODE COMPACT : le mini-panneau flottant lui-même
//   (~340×420px), avec les 3 mêmes onglets à échelle réduite (voir
//   `AgentRoomPanel.tsx`).
// En mode docked/fullscreen ouvert, ce composant ne rend rien : le panneau
// est déjà affiché inline par `AppShell.tsx` (docked) ou en overlay/feuille
// mobile (fullscreen) — un second point d'entrée flottant ferait doublon.

export default function AgentRoomLauncher() {
  const { mode, open, openRoom } = useAgentRoom();

  if (!open) {
    return (
      <Tooltip title="AI Agent Room">
        <Fab
          color="primary"
          onClick={() => openRoom()}
          aria-label="Ouvrir l'AI Agent Room"
          // §piège d'unités MUI (voir AppShell.tsx) — `bottom`/`right` sont
          // des propriétés d'espacement `sx` : un nombre brut serait
          // multiplié par `theme.spacing(1)`, jamais traité comme un pixel
          // direct. Chaînes `"...px"` explicites pour un FAB réellement à
          // 24px du coin, pas à 8×24px.
          sx={{ position: "fixed", bottom: "24px", right: "24px", zIndex: (theme) => theme.zIndex.drawer + 2 }}
        >
          <ForumIcon />
        </Fab>
      </Tooltip>
    );
  }

  if (mode !== "compact") return null;

  return (
    <Paper
      elevation={8}
      sx={{
        position: "fixed",
        bottom: "24px",
        right: "24px",
        width: "min(340px, calc(100vw - 32px))",
        height: "min(440px, calc(100vh - 120px))",
        zIndex: (theme) => theme.zIndex.drawer + 2,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <AgentRoomPanel dense />
    </Paper>
  );
}
