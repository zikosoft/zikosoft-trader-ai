// §B10 "Interrupteur IA dédié dans Settings" (D026, risque R15) — carte
// Settings trouvée manquante lors de l'audit B10 du 28/08 (le contrat
// backend `GET/PUT /api/settings/ai` existait et était testé depuis B10,
// mais aucun écran ne le consommait — `SettingsPage.tsx` le listait
// honnêtement sous "À venir"). Contrairement au kill switch trading
// (`KillSwitchCard.tsx`, confirmation renforcée à phrase tapée), cette
// bascule est réversible et sans effet destructeur — un simple `Switch`
// avec effet immédiat suffit, sur le même principe que tout autre réglage
// applicatif.

import { useEffect, useState } from "react";
import { Alert, Box, Chip, FormControlLabel, Paper, Switch, Typography } from "@mui/material";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import { useLivePolling } from "../../hooks/useLivePolling";
import { fetchAISettings, updateAISettings } from "../../api/aiSettings";
import { describeError } from "../../api/client";
import { useI18n } from "../../i18n/I18nContext";

const POLL_INTERVAL_MS = 10000;

export default function AiGovernanceCard() {
  const { t } = useI18n();
  const { data: settings, refresh } = useLivePolling(fetchAISettings, POLL_INTERVAL_MS);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // État optimiste local pour que le `Switch` réponde immédiatement au
  // clic sans attendre le round-trip réseau (même confort que la plupart
  // des toggles Settings), corrigé par le prochain poll s'il divergeait.
  const [optimisticEnabled, setOptimisticEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    // Un nouveau statut serveur arrive (poll ou refresh) : l'état optimiste
    // n'a plus lieu d'être, la valeur serveur redevient la seule source de
    // vérité — évite qu'un ancien clic optimiste reste affiché après une
    // bascule faite ailleurs (ex. un autre onglet).
    setOptimisticEnabled(null);
  }, [settings?.enabled]);

  const enabled = optimisticEnabled ?? settings?.enabled ?? true;

  async function handleToggle(next: boolean) {
    setOptimisticEnabled(next);
    setPending(true);
    setError(null);
    try {
      await updateAISettings(next);
      refresh();
    } catch (err) {
      setOptimisticEnabled(null);
      setError(describeError(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" component="h2" sx={{ mb: 1, display: "flex", alignItems: "center", gap: 1 }}>
        <SmartToyOutlinedIcon color={enabled ? "primary" : "action"} />
        {t("aiGovernance.title")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        {t("aiGovernance.body")}
      </Typography>

      <Box
        sx={{
          display: "flex",
          flexDirection: { xs: "column", sm: "row" },
          alignItems: { xs: "stretch", sm: "center" },
          justifyContent: "space-between",
          gap: 2,
          mb: settings ? 2 : 0,
        }}
      >
        <FormControlLabel
          control={<Switch checked={enabled} disabled={pending} onChange={(e) => handleToggle(e.target.checked)} />}
          label={enabled ? t("aiGovernance.agentsEnabled") : t("aiGovernance.agentsDisabled")}
        />
        <Chip
          label={enabled ? t("common.active") : t("aiGovernance.off")}
          color={enabled ? "success" : "warning"}
          variant={enabled ? "outlined" : "filled"}
          sx={{ flexShrink: 0 }}
        />
      </Box>

      {settings && (
        <Typography variant="body2" color="text.secondary">
          {t("aiGovernance.quota", {
            calls: settings.max_calls_per_minute,
            highModel: settings.high_stakes_model,
            lowModel: settings.low_stakes_model,
          })}
        </Typography>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}
    </Paper>
  );
}
