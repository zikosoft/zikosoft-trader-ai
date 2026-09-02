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
import { Alert, Box, Button, Chip, FormControlLabel, Paper, Stack, Switch, TextField, Typography } from "@mui/material";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import { useLivePolling } from "../../hooks/useLivePolling";
import { fetchAISettings, updateAISettings, type AISettingsUpdate } from "../../api/aiSettings";
import { describeError } from "../../api/client";
import { useI18n } from "../../i18n/I18nContext";

const POLL_INTERVAL_MS = 10000;

export default function AiGovernanceCard() {
  const { t } = useI18n();
  const { data: settings, refresh } = useLivePolling(fetchAISettings, POLL_INTERVAL_MS);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [draft, setDraft] = useState<AISettingsUpdate>({});
  const [dirty, setDirty] = useState(false);
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

  useEffect(() => {
    if (!settings || dirty) return;
    setDraft({
      max_calls_per_minute: settings.max_calls_per_minute,
      max_calls_per_day: settings.max_calls_per_day,
      high_stakes_model: settings.high_stakes_model,
      low_stakes_model: settings.low_stakes_model,
      temperature: settings.temperature,
      max_tokens: settings.max_tokens,
      timeout_seconds: settings.timeout_seconds,
      daily_budget_usd: settings.daily_budget_usd,
    });
  }, [settings, dirty]);

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

  function changeField<K extends keyof AISettingsUpdate>(key: K, value: AISettingsUpdate[K]) {
    setDirty(true);
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function handleSave() {
    setPending(true);
    setError(null);
    try {
      await updateAISettings({ enabled, ...draft, ...(apiKey ? { api_key: apiKey } : {}) });
      setApiKey("");
      setDirty(false);
      refresh();
    } catch (err) {
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
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t("aiGovernance.quota", {
              calls: settings.max_calls_per_minute,
              highModel: settings.high_stakes_model,
              lowModel: settings.low_stakes_model,
            })}
          </Typography>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>{t("aiGovernance.configuration")}</Typography>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField fullWidth label={t("aiGovernance.highStakesModel")} value={draft.high_stakes_model ?? ""} onChange={(e) => changeField("high_stakes_model", e.target.value)} disabled={pending} />
              <TextField fullWidth label={t("aiGovernance.lowStakesModel")} value={draft.low_stakes_model ?? ""} onChange={(e) => changeField("low_stakes_model", e.target.value)} disabled={pending} />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField type="number" fullWidth label={t("aiGovernance.callsPerMinute")} value={draft.max_calls_per_minute ?? ""} onChange={(e) => changeField("max_calls_per_minute", Number(e.target.value))} inputProps={{ min: 1, max: 10000 }} disabled={pending} />
              <TextField type="number" fullWidth label={t("aiGovernance.callsPerDay")} value={draft.max_calls_per_day ?? ""} onChange={(e) => changeField("max_calls_per_day", Number(e.target.value))} inputProps={{ min: 1, max: 1000000 }} disabled={pending} />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField type="number" fullWidth label={t("aiGovernance.temperature")} value={draft.temperature ?? ""} onChange={(e) => changeField("temperature", Number(e.target.value))} inputProps={{ min: 0, max: 1, step: 0.05 }} disabled={pending} />
              <TextField type="number" fullWidth label={t("aiGovernance.maxTokens")} value={draft.max_tokens ?? ""} onChange={(e) => changeField("max_tokens", Number(e.target.value))} inputProps={{ min: 128, max: 32000 }} disabled={pending} />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField type="number" fullWidth label={t("aiGovernance.timeout")} value={draft.timeout_seconds ?? ""} onChange={(e) => changeField("timeout_seconds", Number(e.target.value))} inputProps={{ min: 1, max: 120 }} disabled={pending} />
              <TextField type="number" fullWidth label={t("aiGovernance.dailyBudget")} value={draft.daily_budget_usd ?? ""} onChange={(e) => changeField("daily_budget_usd", Number(e.target.value))} inputProps={{ min: 0, max: 10000, step: 0.5 }} disabled={pending} />
            </Stack>
            <TextField fullWidth type="password" label={t("aiGovernance.apiKey")} placeholder={settings.api_key_configured ? t("aiGovernance.apiKeyConfigured") : "sk-ant-…"} value={apiKey} onChange={(e) => { setApiKey(e.target.value); setDirty(true); }} disabled={pending} autoComplete="new-password" helperText={t("aiGovernance.apiKeyHelp")} />
            <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
              <Button variant="contained" onClick={handleSave} disabled={pending || !dirty}>{t("common.save")}</Button>
            </Box>
          </Stack>
        </>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}
    </Paper>
  );
}
