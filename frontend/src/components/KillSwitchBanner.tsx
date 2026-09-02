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
import { formatDateTime } from "../i18n/formatters";
import { useI18n } from "../i18n/I18nContext";

const POLL_INTERVAL_MS = 5000;

export default function KillSwitchBanner() {
  const { locale, t } = useI18n();
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
            {t("killSwitchBanner.manage")}
          </Button>
        }
      >
        <AlertTitle sx={{ fontWeight: 700 }}>{t("killSwitchBanner.title")}</AlertTitle>
        {detail?.reason ? t("killSwitchBanner.reason", { reason: detail.reason }) : t("killSwitchBanner.noReason")}
        {" — "}
        {detail?.occurred_at
          ? formatDateTime(locale, detail.occurred_at)
          : t("killSwitchBanner.justNow")}
        . {t("killSwitchBanner.body")}
      </Alert>
    </Box>
  );
}
