// §B09 "Afficher dernière synchronisation" — carte Settings pour le
// catalogue des actifs Alpaca. Même patron que `AiGovernanceCard.tsx`
// (B10) : poll léger de l'état serveur + action manuelle avec état
// optimiste/pending local. Le sync initial a déjà lieu pendant
// l'onboarding (étape `assets_synchronized`) — cette carte sert le
// rafraîchissement manuel ultérieur, pas le premier sync.

import { useState } from "react";
import { Alert, Box, Button, Chip, Paper, Typography } from "@mui/material";
import CategoryOutlinedIcon from "@mui/icons-material/CategoryOutlined";
import { useLivePolling } from "../../hooks/useLivePolling";
import { fetchAssetCatalogStatus, syncAssetCatalog } from "../../api/assets";
import { describeError } from "../../api/client";
import { formatDateTime } from "../../i18n/formatters";
import { useI18n } from "../../i18n/I18nContext";

const POLL_INTERVAL_MS = 30000;

export default function AssetCatalogCard() {
  const { locale, t } = useI18n();
  const { data: status, refresh } = useLivePolling(fetchAssetCatalogStatus, POLL_INTERVAL_MS);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResultNote, setLastResultNote] = useState<string | null>(null);

  async function handleSync() {
    setSyncing(true);
    setError(null);
    setLastResultNote(null);
    try {
      const result = await syncAssetCatalog();
      setLastResultNote(
        t("assetCatalog.syncResult", {
          created: result.created_count,
          updated: result.updated_count,
          deactivated: result.deactivated_count,
        }),
      );
      refresh();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSyncing(false);
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" component="h2" sx={{ mb: 1, display: "flex", alignItems: "center", gap: 1 }}>
        <CategoryOutlinedIcon color="primary" />
        {t("assetCatalog.title")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        {t("assetCatalog.body")}
      </Typography>

      <Box
        sx={{
          display: "flex",
          flexDirection: { xs: "column", sm: "row" },
          alignItems: { xs: "stretch", sm: "center" },
          justifyContent: "space-between",
          gap: 2,
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
          <Chip
            label={t("assetCatalog.activeCount", { count: status?.active_asset_count ?? 0 })}
            size="small"
            variant="outlined"
          />
          <Typography variant="body2" color="text.secondary">
            {t("assetCatalog.lastSync", {
              time: status?.last_synced_at ? formatDateTime(locale, status.last_synced_at) : t("assetCatalog.never"),
            })}
          </Typography>
        </Box>
        <Button variant="outlined" disabled={syncing} onClick={handleSync} sx={{ flexShrink: 0 }}>
          {syncing ? t("assetCatalog.syncing") : t("assetCatalog.resync")}
        </Button>
      </Box>

      {lastResultNote && (
        <Alert severity="success" sx={{ mt: 2 }}>
          {lastResultNote}
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}
    </Paper>
  );
}
