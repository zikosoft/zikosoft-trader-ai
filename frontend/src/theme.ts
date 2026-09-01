import { createTheme, type ThemeOptions } from "@mui/material/styles";

// §B25 "Day/night" + décision D059 (voir AVANCEMENT.md) : une seule palette
// de marque (couleurs de contexte REPLAY/PAPER héritées de
// `ContextSwitcher.tsx`, B06 ; rouge d'incident hérité de
// `IncidentBanner.css`, B23) déclinée en mode clair ET sombre, plutôt que
// deux palettes indépendantes — garantit que les couleurs "métier" déjà
// significatives pour Zac (vert PAPER, ambre REPLAY, rouge incident) restent
// reconnaissables identiquement dans les deux modes.

const PAPER_COLOR = "#0a7d32";
const REPLAY_COLOR = "#7d5a00";
export const INCIDENT_COLOR = "#b3261e";

const shared: ThemeOptions = {
  typography: {
    fontFamily: [
      "-apple-system",
      "BlinkMacSystemFont",
      '"Segoe UI"',
      "Roboto",
      '"Helvetica Neue"',
      "Arial",
      "sans-serif",
    ].join(","),
  },
  shape: { borderRadius: 8 },
  components: {
    // §Qualité "Navigation clavier" : le focus visible par défaut de MUI
    // est déjà correct — évite toute personnalisation `outline: none` qui
    // supprimerait cette affordance ailleurs dans l'app (aucune ici).
    MuiButtonBase: { defaultProps: { disableRipple: false } },
  },
};

export function buildTheme(mode: "light" | "dark") {
  return createTheme({
    ...shared,
    palette: {
      mode,
      primary: { main: mode === "dark" ? "#5b9bd5" : "#0a63c2" },
      success: { main: PAPER_COLOR },
      warning: { main: REPLAY_COLOR },
      error: { main: INCIDENT_COLOR },
      background:
        mode === "dark" ? { default: "#0f1115", paper: "#171a21" } : { default: "#f5f6f8", paper: "#ffffff" },
    },
  });
}

export const CONTEXT_COLORS = { PAPER: PAPER_COLOR, REPLAY: REPLAY_COLOR };

// §B28 "Agent Room" (décision D074, voir AVANCEMENT.md) : même principe que
// D059 ci-dessus — une couleur fixe par `agent_type` (colonne réelle de
// `agent_messages`, jamais un intitulé fabriqué), reconnaissable
// identiquement en mode clair ET sombre dans le fil "Live Debate". Les
// QUATRE valeurs possibles sont celles réellement écrites en base (voir
// `agents/strategy_agent/main.py`, `agents/risk_critic_agent/main.py`,
// `workers/risk_engine/main.py`, `agents/execution_explanation_agent/main.py`)
// — aucune cinquième valeur n'existe dans le pipeline actuel.
export const AGENT_COLORS: Record<string, string> = {
  strategy_agent: "#0a63c2",
  risk_critic_agent: "#c26b00",
  risk_engine: "#6a1b9a",
  execution_explanation_agent: "#1b8a5a",
};
