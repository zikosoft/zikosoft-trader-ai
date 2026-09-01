import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  List,
  ListItem,
  ListItemText,
  Paper,
  Skeleton,
  Switch,
  FormControlLabel,
  Typography,
} from "@mui/material";
import { useLivePolling } from "../hooks/useLivePolling";
import { fetchAlerts, markAlertRead, markAllAlertsRead, type AlertItem, type AlertSeverity } from "../api/alerts";
import { ApiError, describeError } from "../api/client";

// §B20 — écran dédié Alerts, remplace l'état vide honnête posé en B25
// ("l'Alert Dispatcher n'existe pas encore") maintenant que
// `alert_worker`/`kill_switch.py` écrivent réellement des lignes `Alert`.
// Même isolation par contexte d'exécution actif que le reste de l'app
// (`backend/app/routers/alerts.py`) — les alertes affichées ici sont
// toujours celles du contexte Paper/Replay actuellement sélectionné.

const POLL_INTERVAL_MS = 10000;

function severityColor(severity: AlertSeverity): "error" | "warning" | "info" {
  if (severity === "CRITICAL") return "error";
  if (severity === "WARNING") return "warning";
  return "info";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("fr-FR");
}

export default function AlertsPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { data, error, loading, refresh } = useLivePolling(
    () => fetchAlerts({ unreadOnly, limit: 50 }),
    POLL_INTERVAL_MS,
  );
  const [markingAll, setMarkingAll] = useState(false);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());

  async function handleMarkRead(alert: AlertItem) {
    if (alert.is_read) return;
    setPendingIds((prev) => new Set(prev).add(alert.id));
    try {
      await markAlertRead(alert.id);
      refresh();
    } finally {
      setPendingIds((prev) => {
        const next = new Set(prev);
        next.delete(alert.id);
        return next;
      });
    }
  }

  async function handleMarkAllRead() {
    setMarkingAll(true);
    try {
      await markAllAlertsRead();
      refresh();
    } finally {
      setMarkingAll(false);
    }
  }

  if (loading && !data && !error) {
    return (
      <Box sx={{ maxWidth: 720 }}>
        <Skeleton variant="text" width={220} height={48} sx={{ mb: 2 }} />
        <Skeleton variant="rectangular" height={300} sx={{ borderRadius: 1 }} />
      </Box>
    );
  }

  if (!data && error instanceof ApiError && error.code === "VALIDATION_ERROR") {
    return (
      <Box sx={{ maxWidth: 720 }}>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          Alerts
        </Typography>
        <Alert severity="info">Aucun contexte d'exécution actif — choisis d'abord un contexte (Paper ou Replay).</Alert>
      </Box>
    );
  }

  if (!data && error) {
    return (
      <Box sx={{ maxWidth: 720 }}>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          Alerts
        </Typography>
        <Alert severity="error">{describeError(error)}</Alert>
      </Box>
    );
  }

  const alerts = data?.alerts ?? [];
  const hasUnread = alerts.some((a) => !a.is_read);

  return (
    <Box sx={{ maxWidth: 720 }}>
      <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
        Alerts
      </Typography>

      {error !== null && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {describeError(error)} — dernières données connues affichées ci-dessous.
        </Alert>
      )}

      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 2, flexWrap: "wrap", gap: 1 }}>
        <FormControlLabel
          control={<Switch checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />}
          label="Non lues uniquement"
        />
        <Button size="small" variant="outlined" disabled={!hasUnread || markingAll} onClick={handleMarkAllRead}>
          {markingAll ? "…" : "Tout marquer comme lu"}
        </Button>
      </Box>

      <Paper variant="outlined">
        {alerts.length === 0 ? (
          <Box sx={{ p: 3 }}>
            <Typography color="text.secondary">
              {unreadOnly ? "Aucune alerte non lue." : "Aucune alerte pour ce contexte."}
            </Typography>
          </Box>
        ) : (
          <List disablePadding>
            {alerts.map((alert, i) => (
              <ListItem
                key={alert.id}
                divider={i < alerts.length - 1}
                onClick={() => handleMarkRead(alert)}
                sx={{
                  cursor: alert.is_read ? "default" : "pointer",
                  bgcolor: alert.is_read ? "transparent" : "action.hover",
                  opacity: pendingIds.has(alert.id) ? 0.6 : 1,
                  alignItems: "flex-start",
                }}
              >
                <ListItemText
                  primary={
                    <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
                      <Chip label={alert.severity} size="small" color={severityColor(alert.severity)} />
                      <Chip label={alert.category} size="small" variant="outlined" />
                      <Typography component="span" sx={{ fontWeight: alert.is_read ? 400 : 600 }}>
                        {alert.title}
                      </Typography>
                      {!alert.is_read && <Chip label="non lue" size="small" color="primary" variant="outlined" />}
                    </Box>
                  }
                  secondary={
                    <>
                      <Typography component="span" variant="body2" color="text.secondary" sx={{ display: "block" }}>
                        {alert.message}
                      </Typography>
                      <Typography component="span" variant="caption" color="text.secondary">
                        {formatDate(alert.created_at)}
                      </Typography>
                    </>
                  }
                />
              </ListItem>
            ))}
          </List>
        )}
      </Paper>
    </Box>
  );
}
