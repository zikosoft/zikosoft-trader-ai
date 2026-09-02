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
import { formatDateTime } from "../i18n/formatters";
import { useI18n } from "../i18n/I18nContext";
import { localizeValue } from "../i18n/domain";

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

export default function AlertsPage() {
  const { locale, t } = useI18n();
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
          {t("navigation.alerts")}
        </Typography>
        <Alert severity="info">{t("context.activeRequired")}</Alert>
      </Box>
    );
  }

  if (!data && error) {
    return (
      <Box sx={{ maxWidth: 720 }}>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.alerts")}
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
        {t("navigation.alerts")}
      </Typography>

      {error !== null && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("common.showingLastKnownData", { error: describeError(error) })}
        </Alert>
      )}

      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 2, flexWrap: "wrap", gap: 1 }}>
        <FormControlLabel
          control={<Switch checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />}
          label={t("alerts.unreadOnly")}
        />
        <Button size="small" variant="outlined" disabled={!hasUnread || markingAll} onClick={handleMarkAllRead}>
          {markingAll ? "…" : t("alerts.markAllRead")}
        </Button>
      </Box>

      <Paper variant="outlined">
        {alerts.length === 0 ? (
          <Box sx={{ p: 3 }}>
            <Typography color="text.secondary">
              {unreadOnly ? t("alerts.noUnread") : t("alerts.empty")}
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
                      <Chip label={localizeValue(t, `alertSeverity.${alert.severity}`, alert.severity)} size="small" color={severityColor(alert.severity)} />
                      <Chip label={localizeValue(t, `alertCategory.${alert.category}`, alert.category)} size="small" variant="outlined" />
                      <Typography component="span" sx={{ fontWeight: alert.is_read ? 400 : 600 }}>
                        {alert.title}
                      </Typography>
                      {!alert.is_read && <Chip label={t("alerts.unread")} size="small" color="primary" variant="outlined" />}
                    </Box>
                  }
                  secondary={
                    <>
                      <Typography component="span" variant="body2" color="text.secondary" sx={{ display: "block" }}>
                        {alert.message}
                      </Typography>
                      <Typography component="span" variant="caption" color="text.secondary">
                        {formatDateTime(locale, alert.created_at)}
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
