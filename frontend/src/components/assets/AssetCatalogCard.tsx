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

const POLL_INTERVAL_MS = 30000;

function formatDate(iso: string | null): string {
  if (!iso) return "jamais";
  return new Date(iso).toLocaleString("fr-FR");
}

export default function AssetCatalogCard() {
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
        `${result.created_count} créé(s), ${result.updated_count} mis à jour, ${result.deactivated_count} désactivé(s).`,
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
        Catalogue des actifs
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Symboles Alpaca disponibles pour la création de stratégies (autocomplete). Synchronisé automatiquement pendant
        la connexion du compte — un rafraîchissement manuel n'est utile que pour prendre en compte un changement récent
        du côté d'Alpaca (nouveaux actifs, retraits, statut négociable modifié).
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
          <Chip label={`${status?.active_asset_count ?? 0} actif(s) au catalogue`} size="small" variant="outlined" />
          <Typography variant="body2" color="text.secondary">
            Dernière synchronisation : {formatDate(status?.last_synced_at ?? null)}
          </Typography>
        </Box>
        <Button variant="outlined" disabled={syncing} onClick={handleSync} sx={{ flexShrink: 0 }}>
          {syncing ? "Synchronisation…" : "Resynchroniser"}
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
