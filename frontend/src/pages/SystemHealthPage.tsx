import RefreshIcon from "@mui/icons-material/Refresh";
import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { fetchSystemHealth, SERVICE_LABELS, type ServiceCheckStatus, type SystemHealth } from "../api/systemHealth";
import { useLivePolling } from "../hooks/useLivePolling";
import { formatDateTime } from "../i18n/formatters";
import { useI18n } from "../i18n/I18nContext";
import { serviceLabel } from "../i18n/domain";

// §B25 "System Health" (menu gauche) — première page de ce shell à afficher
// des données RÉELLES plutôt qu'un placeholder : `GET /api/system/health`
// existe, est testé de bout en bout et livré depuis B22/B23 ; rien n'empêche
// de lui donner un écran dédié complet dès maintenant, contrairement aux
// 9 autres destinations du menu qui attendent chacune leur propre brique de
// contenu. Utilise `useLivePolling` (nouveau, §B25 "Client événements temps
// réel", décision D058) — même cadence (5s) que `IncidentBanner.tsx` (B23),
// qui garde volontiers sa propre boucle indépendante.

const STATUS_COLOR: Record<ServiceCheckStatus, "success" | "warning" | "error" | "default"> = {
  HEALTHY: "success",
  STARTING: "default",
  DEGRADED: "warning",
  DISCONNECTED: "error",
};

const POLL_INTERVAL_MS = 5000;

export default function SystemHealthPage() {
  const { locale, t } = useI18n();
  const { data, error, loading, refresh } = useLivePolling<SystemHealth>(fetchSystemHealth, POLL_INTERVAL_MS);

  return (
    <Box sx={{ maxWidth: 960 }}>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 2 }}>
        <Typography variant="h4" component="h1">
          {t("navigation.systemHealth")}
        </Typography>
        <Button startIcon={<RefreshIcon />} onClick={refresh} variant="outlined" size="small">
          {t("common.refresh")}
        </Button>
      </Box>

      {loading && !data && (
        <Box>
          {Array.from({ length: 9 }).map((_, i) => (
            <Skeleton key={i} variant="rectangular" height={36} sx={{ mb: 0.5, borderRadius: 1 }} />
          ))}
        </Box>
      )}

      {error !== null && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {t("incident.backendUnreachable")}
        </Alert>
      )}

      {data && (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("systemHealth.service")}</TableCell>
                <TableCell>{t("common.status")}</TableCell>
                <TableCell>{t("systemHealth.latency")}</TableCell>
                <TableCell>{t("systemHealth.lastHeartbeat")}</TableCell>
                <TableCell>{t("common.details")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {Object.entries(data.checks).map(([name, check]) => (
                <TableRow key={name}>
                  <TableCell>{serviceLabel(t, name, SERVICE_LABELS[name] ?? name)}</TableCell>
                  <TableCell>
                    <Chip
                      label={t(`status.${check.status}`)}
                      color={STATUS_COLOR[check.status] ?? "default"}
                      size="small"
                      variant={check.status === "HEALTHY" ? "filled" : "outlined"}
                    />
                  </TableCell>
                  <TableCell>{check.latency_ms !== undefined ? `${check.latency_ms} ms` : "—"}</TableCell>
                  <TableCell>
                    {check.last_heartbeat_at
                      ? formatDateTime(locale, check.last_heartbeat_at, { timeStyle: "short" })
                      : "—"}
                  </TableCell>
                  <TableCell>{check.error ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
}
