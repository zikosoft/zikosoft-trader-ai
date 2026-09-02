import { Alert, Box, Chip, List, ListItem, ListItemText, Paper, Skeleton, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { useLivePolling } from "../../hooks/useLivePolling";
import { fetchSystemHealth } from "../../api/systemHealth";
import { fetchAlerts, type AlertSeverity } from "../../api/alerts";
import { fetchBars, fetchSymbols, type BarsResponse } from "../../api/market";
import { useThemeMode } from "../../useThemeMode";
import SparklineChart from "../market/SparklineChart";
import { useI18n } from "../../i18n/I18nContext";
import { localizeValue } from "../../i18n/domain";

// §B26 "Santé système" + "Kill switch" — même poll (`/api/system/health`,
// B22/B23/B25) réutilisé pour les deux : le flag kill switch voyage déjà
// dans cette même réponse (voir `backend/app/main.py`, ajout B26), inutile
// de poller deux fois.
//
// §B20 — "Alertes" n'est plus un placeholder : les 3 alertes les plus
// récentes du contexte actif (`GET /api/alerts`, même endpoint que
// `AlertsPage.tsx`), maintenant qu'`alert_worker`/`kill_switch.py`
// écrivent réellement des lignes `Alert`.
//
// §B27 "Market chart" — n'est plus un placeholder : aperçu réel (sparkline)
// du premier symbole ayant des bougies persistées (voir
// `backend/app/market.py::list_symbols`), lien vers l'écran Market complet
// (chandeliers/volume/marqueurs). Reste honnêtement vide tant qu'aucun
// symbole n'a de bougie (Market Agent pas encore passé pour ce symbole).

const STATUS_COLOR: Record<string, "success" | "warning" | "error" | "default"> = {
  HEALTHY: "success",
  DEGRADED: "warning",
  DISCONNECTED: "error",
  STARTING: "default",
};

export function SystemHealthAndKillSwitchCard() {
  const { t } = useI18n();
  const { data, loading } = useLivePolling(fetchSystemHealth, 5000);

  if (loading && !data) return <Skeleton variant="rectangular" height={140} sx={{ borderRadius: 1 }} />;

  return (
    <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1.5 }}>
        <Typography variant="h6" component="h2">
          {t("systemHealth.title")}
        </Typography>
        <Chip
          component={RouterLink}
          to="/system-health"
          clickable
          label={data ? localizeValue(t, `status.${data.status.toUpperCase()}`, data.status) : "…"}
          size="small"
          color={data ? (STATUS_COLOR[data.status] ?? "default") : "default"}
        />
      </Box>

      {/* §B31 — l'indicateur redevient une VRAIE action : la carte complète
          (confirmation renforcée, annulation des ordres ouverts, audit
          event, alertes) vit maintenant dans Settings (`KillSwitchCard.tsx`)
          — ce chip pointe donc vers `/settings`, même pattern que le chip
          "Santé système" ci-dessus (posé en B26, inchangé). */}
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography variant="body2" color="text.secondary">
          {t("killSwitch.shortTitle")}
        </Typography>
        {data?.trading_kill_switch_engaged === null || data?.trading_kill_switch_engaged === undefined ? (
          <Chip component={RouterLink} to="/settings" clickable label={t("common.unknown")} size="small" />
        ) : data.trading_kill_switch_engaged ? (
          <Chip component={RouterLink} to="/settings" clickable label={t("killSwitch.tradingSuspended")} size="small" color="error" />
        ) : (
          <Chip
            component={RouterLink}
            to="/settings"
            clickable
            label={t("killSwitch.tradingActive")}
            size="small"
            color="success"
            variant="outlined"
          />
        )}
      </Box>
    </Paper>
  );
}

function alertSeverityColor(severity: AlertSeverity): "error" | "warning" | "info" {
  if (severity === "CRITICAL") return "error";
  if (severity === "WARNING") return "warning";
  return "info";
}

export function AlertsWidgetCard() {
  const { t } = useI18n();
  const { data, loading, error } = useLivePolling(() => fetchAlerts({ limit: 3 }), 10000);

  return (
    <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
        <Typography variant="h6" component="h2">
          {t("navigation.alerts")}
        </Typography>
        <Chip component={RouterLink} to="/alerts" clickable label={t("common.viewAll")} size="small" variant="outlined" />
      </Box>
      {loading && !data ? (
        <Skeleton variant="rectangular" height={72} sx={{ borderRadius: 1 }} />
      ) : !data && error ? (
        <Alert severity="info" sx={{ "& .MuiAlert-message": { fontSize: "0.875rem" } }}>
          {t("context.activeRequiredShort")}
        </Alert>
      ) : !data || data.alerts.length === 0 ? (
        <Typography color="text.secondary" sx={{ fontSize: "0.875rem" }}>
          {t("alerts.empty")}
        </Typography>
      ) : (
        <List dense disablePadding>
          {data.alerts.map((a) => (
            <ListItem key={a.id} disableGutters divider>
              <ListItemText
                primary={
                  <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                    <Chip label={localizeValue(t, `alertSeverity.${a.severity}`, a.severity)} size="small" color={alertSeverityColor(a.severity)} />
                    <Typography
                      component="span"
                      variant="body2"
                      sx={{ fontWeight: a.is_read ? 400 : 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                    >
                      {a.title}
                    </Typography>
                  </Box>
                }
              />
            </ListItem>
          ))}
        </List>
      )}
    </Paper>
  );
}

async function fetchFirstSymbolBars(): Promise<BarsResponse | null> {
  const symbols = await fetchSymbols();
  if (symbols.length === 0) return null;
  return fetchBars(symbols[0], "1Day", 30);
}

export function MarketWidgetCard() {
  const { t } = useI18n();
  const { data, loading } = useLivePolling(fetchFirstSymbolBars, 15000);
  const { mode } = useThemeMode();

  return (
    <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
        <Typography variant="h6" component="h2">
          {t("navigation.market")}
        </Typography>
        <Chip component={RouterLink} to="/market" clickable label={t("common.viewAll")} size="small" variant="outlined" />
      </Box>
      {loading && !data ? (
        <Skeleton variant="rectangular" height={72} sx={{ borderRadius: 1 }} />
      ) : !data || data.bars.length === 0 ? (
        <Typography color="text.secondary">
          {t("market.noData")}
        </Typography>
      ) : (
        <Box>
          <Typography variant="body2" sx={{ mb: 0.5 }}>
            {data.symbol} — {data.bars[data.bars.length - 1].close.toFixed(2)} $
          </Typography>
          <SparklineChart
            themeMode={mode}
            color="auto"
            points={data.bars.map((b) => ({ x: b.bar_at, y: b.close }))}
          />
        </Box>
      )}
    </Paper>
  );
}
