// Read-only options discovery for the Paper Trading demo. It deliberately
// uses the same authenticated backend endpoints as the option-selection
// worker, but has no order action and therefore cannot bypass risk controls.

import { useState } from "react";
import { Alert, Box, Button, Chip, Paper, Stack, TextField, Typography } from "@mui/material";
import TravelExploreOutlinedIcon from "@mui/icons-material/TravelExploreOutlined";
import { describeError } from "../../api/client";
import { fetchOptionChain, syncOptionContracts } from "../../api/assets";
import { useI18n } from "../../i18n/I18nContext";

export default function OptionsDiscoveryCard() {
  const { t } = useI18n();
  const [underlying, setUnderlying] = useState("AAPL");
  const [syncing, setSyncing] = useState(false);
  const [loadingChain, setLoadingChain] = useState(false);
  const [resultNote, setResultNote] = useState<string | null>(null);
  const [chainCount, setChainCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const normalizedUnderlying = underlying.trim().toUpperCase();
  const invalidUnderlying = normalizedUnderlying.length === 0;

  async function handleSync() {
    if (invalidUnderlying) return;
    setSyncing(true);
    setError(null);
    setResultNote(null);
    try {
      const result = await syncOptionContracts(normalizedUnderlying);
      setResultNote(t("optionsDiscovery.syncResult", { count: result.synced_count, symbol: result.underlying_symbol }));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSyncing(false);
    }
  }

  async function handleLoadChain() {
    if (invalidUnderlying) return;
    setLoadingChain(true);
    setError(null);
    setChainCount(null);
    try {
      const result = await fetchOptionChain(normalizedUnderlying);
      setChainCount(result.snapshots.length);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoadingChain(false);
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" component="h2" sx={{ mb: 1, display: "flex", alignItems: "center", gap: 1 }}>
        <TravelExploreOutlinedIcon color="primary" />
        {t("optionsDiscovery.title")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        {t("optionsDiscovery.body")}
      </Typography>

      <Box sx={{ display: "flex", flexDirection: { xs: "column", sm: "row" }, gap: 1.25, alignItems: { sm: "center" } }}>
        <TextField
          label={t("optionsDiscovery.underlying")}
          value={underlying}
          onChange={(event) => setUnderlying(event.target.value.toUpperCase())}
          inputProps={{ maxLength: 10, "aria-label": t("optionsDiscovery.underlying") }}
          size="small"
          sx={{ maxWidth: { sm: 180 } }}
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <Button variant="outlined" onClick={handleSync} disabled={syncing || invalidUnderlying}>
            {syncing ? t("optionsDiscovery.syncing") : t("optionsDiscovery.sync")}
          </Button>
          <Button variant="outlined" onClick={handleLoadChain} disabled={loadingChain || invalidUnderlying}>
            {loadingChain ? t("optionsDiscovery.loadingChain") : t("optionsDiscovery.loadChain")}
          </Button>
        </Stack>
      </Box>

      {chainCount !== null && (
        <Chip label={t("optionsDiscovery.chainCount", { count: chainCount })} size="small" variant="outlined" sx={{ mt: 2 }} />
      )}
      {resultNote && <Alert severity="success" sx={{ mt: 2 }}>{resultNote}</Alert>}
      {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 2 }}>
        {t("optionsDiscovery.readOnly")}
      </Typography>
    </Paper>
  );
}
