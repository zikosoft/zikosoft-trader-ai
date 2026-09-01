import { useEffect, useState } from "react";
import { Alert, Box, Button, Chip, Grid, Paper, Skeleton, Typography } from "@mui/material";
import { useNavigate } from "react-router-dom";
import { fetchOnboardingStatus, type OnboardingStatus } from "../../api/onboarding";
import { fetchStrategyDefinitions, type StrategyDefinition } from "../../api/strategies";
import { selectContext, type ContextListResponse } from "../../api/context";
import type { PortfolioSummary } from "../../api/portfolio";

const CURRENCY = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

// §B26 "Dashboard sans activité" — état honnête affiché tant qu'aucun tour
// du Portfolio Worker n'a encore eu lieu pour le contexte actif
// (`GET /api/portfolio/summary` répond 404, voir `OverviewPage.tsx`).
// Règle directrice de toute cette vue : "Ne montrer aucune performance
// fictive" — chaque chiffre affiché ici vient d'une VRAIE source (catalogue
// de stratégies réel ; solde de compte lu depuis `GET /api/onboarding/status`,
// qui dérive lui-même du dernier `portfolio_snapshot` du Portfolio Worker,
// voir `backend/app/routers/onboarding.py::_latest_balance` — donc lui
// aussi honnêtement absent tant qu'aucun tour n'a eu lieu, jamais un
// placeholder numérique qui prétendrait représenter un compte.
export default function ColdStartView({
  contextState,
  onContextChanged,
  summary = null,
}: {
  contextState: ContextListResponse;
  onContextChanged: (state: ContextListResponse) => void;
  // §B26 — quand fourni (compte connecté, Portfolio Worker déjà passé une
  // fois, mais 100 % cash / aucune position), ce résumé RÉEL remplace le
  // solde dérivé de l'onboarding (`GET /api/onboarding/status`, qui
  // dépendrait du même snapshot de toute façon) — préféré ici car déjà
  // chargé par `OverviewPage`, aucune requête supplémentaire.
  summary?: PortfolioSummary | null;
}) {
  const navigate = useNavigate();
  const isPaper = contextState.active_kind === "PAPER";

  const [onboarding, setOnboarding] = useState<OnboardingStatus | null | undefined>(undefined);
  const [definitions, setDefinitions] = useState<StrategyDefinition[] | null>(null);
  const [switching, setSwitching] = useState(false);

  useEffect(() => {
    if (!isPaper) return;
    fetchOnboardingStatus()
      .then(setOnboarding)
      .catch(() => setOnboarding(null));
  }, [isPaper]);

  useEffect(() => {
    fetchStrategyDefinitions()
      .then(setDefinitions)
      .catch(() => setDefinitions([]));
  }, []);

  async function handleLaunchReplay() {
    setSwitching(true);
    try {
      const result = await selectContext("REPLAY");
      if ("confirmationRequired" in result) {
        // §B06 — même règle de confirmation qu'ailleurs ; rejoué avec confirm=true
        // directement ici puisque l'intention ("Launch Replay") est déjà explicite.
        const confirmed = await selectContext("REPLAY", true);
        if (!("confirmationRequired" in confirmed)) onContextChanged(confirmed);
      } else {
        onContextChanged(result);
      }
    } finally {
      setSwitching(false);
    }
  }

  const cash = summary?.cash ?? onboarding?.account?.balance?.cash ?? null;
  const agentsReady = onboarding?.steps.find((s) => s.step_code === "ai_agents_ready")?.status === "COMPLETED";

  return (
    <Box>
      <Typography variant="h4" component="h1" sx={{ mb: 1 }}>
        Overview
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Pas encore d'activité sur ce contexte — aucune performance n'est encore disponible.
      </Typography>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
            <Typography variant="h6" component="h2" sx={{ mb: 1.5 }}>
              Compte
            </Typography>
            {isPaper ? (
              onboarding === undefined ? (
                <Skeleton variant="rectangular" height={90} sx={{ borderRadius: 1 }} />
              ) : (
                <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
                  <Chip label="Compte Alpaca Paper connecté" color="success" size="small" sx={{ width: "fit-content" }} />
                  <Typography>
                    Cash :{" "}
                    <strong>{cash !== null ? CURRENCY.format(cash) : "non disponible pour l'instant"}</strong>
                  </Typography>
                  {cash !== null && (
                    <Chip label="100 % Cash — aucune position ouverte" size="small" variant="outlined" sx={{ width: "fit-content" }} />
                  )}
                  <Typography color="text.secondary" variant="body2">
                    Agents IA : {agentsReady ? "prêts" : "pas encore prêts"}
                  </Typography>
                </Box>
              )
            ) : (
              <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <Chip label="Contexte Historical Replay actif" color="warning" size="small" sx={{ width: "fit-content" }} />
                {cash !== null ? (
                  <>
                    <Typography>
                      Cash : <strong>{CURRENCY.format(cash)}</strong>
                    </Typography>
                    <Chip label="100 % Cash — aucune position ouverte" size="small" variant="outlined" sx={{ width: "fit-content" }} />
                  </>
                ) : (
                  <Typography color="text.secondary">
                    Aucun compte Alpaca requis en Replay — les métriques de portefeuille pour ce contexte ne sont
                    pas encore disponibles (Replay Engine, B19, encore à l'étape squelette).
                  </Typography>
                )}
              </Box>
            )}
            <Typography color="text.secondary" variant="body2" sx={{ mt: 1.5 }}>
              État marché : non disponible pour l'instant (aucun endpoint de statut marché ne construit encore
              cette donnée — voir B26/B27).
            </Typography>
          </Paper>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
            <Typography variant="h6" component="h2" sx={{ mb: 1.5 }}>
              Stratégies disponibles
            </Typography>
            {definitions === null ? (
              <Skeleton variant="rectangular" height={90} sx={{ borderRadius: 1 }} />
            ) : definitions.length === 0 ? (
              <Typography color="text.secondary">Aucune stratégie disponible pour le moment.</Typography>
            ) : (
              <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
                {definitions.map((d) => (
                  <Chip key={d.id} label={d.name} size="small" variant="outlined" />
                ))}
              </Box>
            )}
          </Paper>
        </Grid>
      </Grid>

      <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
        <Button variant="contained" onClick={() => navigate("/strategies")}>
          Create Strategy
        </Button>
        {!isPaper ? null : (
          <Button variant="outlined" disabled={switching} onClick={handleLaunchReplay}>
            Launch Replay
          </Button>
        )}
      </Box>

      {!isPaper && (
        <Alert severity="info" sx={{ mt: 3, maxWidth: 640 }}>
          Contexte Historical Replay déjà actif.
        </Alert>
      )}
    </Box>
  );
}
