// §B31 "Bouton global très visible" / "Alerte in-app" — bannière globale,
// non fermable tant que le trading est suspendu, montée à côté (jamais À
// LA PLACE) de `IncidentBanner.tsx` (B23) : un kill switch engagé est une
// action de sécurité DÉLIBÉRÉE, distincte d'un incident système non
// planifié (D056) — copie et icône volontairement différentes pour que
// personne ne les confonde. Réutilise le même flux public déjà pollé pour
// le kill switch (`GET /api/system/health`, `trading_kill_switch_detail`,
// backend/app/main.py) plutôt qu'une route dédiée supplémentaire.
//
// Contrairement à `IncidentBanner.tsx` (pré-MUI, B23), ce composant est
// écrit avec Material UI directement — même convention que tout le reste
// du frontend depuis B25.

import { Alert, AlertTitle, Box, Button } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { useLivePolling } from "../hooks/useLivePolling";
import { fetchSystemHealth } from "../api/systemHealth";

const POLL_INTERVAL_MS = 5000;

function formatOccurredAt(iso: string | null): string {
  if (!iso) return "à l'instant";
  try {
    return new Date(iso).toLocaleString("fr-FR");
  } catch {
    return iso;
  }
}

export default function KillSwitchBanner() {
  const { data } = useLivePolling(fetchSystemHealth, POLL_INTERVAL_MS);

  if (!data?.trading_kill_switch_engaged) return null;

  const detail = data.trading_kill_switch_detail;

  return (
    <Box sx={{ position: "sticky", top: 0, zIndex: (theme) => theme.zIndex.drawer + 3 }} role="alert">
      <Alert
        severity="error"
        variant="filled"
        sx={{ borderRadius: 0 }}
        action={
          <Button component={RouterLink} to="/settings" color="inherit" size="small" variant="outlined">
            Gérer
          </Button>
        }
      >
        <AlertTitle sx={{ fontWeight: 700 }}>Trading suspendu — Kill switch engagé</AlertTitle>
        {detail?.reason ? `Raison : « ${detail.reason} »` : "Aucune raison enregistrée."}
        {" — "}
        {formatOccurredAt(detail?.occurred_at ?? null)}. Aucune nouvelle proposition ni aucun nouvel ordre tant que le
        trading n'est pas explicitement repris.
      </Alert>
    </Box>
  );
}
