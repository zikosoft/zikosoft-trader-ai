import {
  Alert,
  Box,
  Chip,
  Paper,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { useLivePolling } from "../hooks/useLivePolling";
import { fetchRecentOrders } from "../api/orders";
import { ApiError, describeError } from "../api/client";
import { formatCurrency, formatDateTime } from "../i18n/formatters";
import { useI18n } from "../i18n/I18nContext";
import { localizeValue } from "../i18n/domain";
import OptionInstrumentSummary from "../components/options/OptionInstrumentSummary";

// §écran dédié Orders (28/08 — fermeture des liens de menu, voir
// AVANCEMENT.md) — remplace le `PlaceholderPage` qui pointait vers le
// widget dashboard "Ordres récents" (B26). Route déjà servie par le
// backend depuis B17/B26 (`GET /api/orders/recent`) : cet écran ne fait
// qu'afficher les MAX_RECENT_LIMIT=50 dernières lignes en table complète
// au lieu des 5 lignes condensées du widget — aucune nouvelle route
// backend. La pagination réelle au-delà de 50 lignes reste un gap honnête
// (voir `backend/app/routers/orders.py`, docstring d'origine) : documenté
// dans AVANCEMENT.md plutôt que masqué.

function statusColor(status: string): "success" | "error" | "warning" | "default" {
  const s = status.toLowerCase();
  if (s === "filled") return "success";
  if (s === "canceled" || s === "cancelled" || s === "rejected" || s === "expired") return "error";
  if (s === "pending_new" || s === "new" || s === "accepted" || s === "partially_filled") return "warning";
  return "default";
}

export default function OrdersPage() {
  const { locale, t } = useI18n();
  const { data, error, loading } = useLivePolling(() => fetchRecentOrders(50), 5000);

  if (loading && !data && !error) {
    return (
      <Box>
        <Skeleton variant="text" width={220} height={48} sx={{ mb: 2 }} />
        <Skeleton variant="rectangular" height={400} sx={{ borderRadius: 1 }} />
      </Box>
    );
  }

  if (!data && error instanceof ApiError && error.code === "VALIDATION_ERROR") {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.orders")}
        </Typography>
        <Alert severity="info">{t("context.activeRequired")}</Alert>
      </Box>
    );
  }

  if (!data && error) {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.orders")}
        </Typography>
        <Alert severity="error">{describeError(error)}</Alert>
      </Box>
    );
  }

  const orders = data?.orders ?? [];

  return (
    <Box>
      <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
        {t("navigation.orders")}
      </Typography>

      {error !== null && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("common.showingLastKnownData", { error: describeError(error) })}
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 2 }}>
        {orders.length === 0 ? (
          <Typography color="text.secondary">{t("orders.empty")}</Typography>
        ) : (
          <>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {t("orders.recentCount", { count: orders.length })}
            </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("common.symbol")}</TableCell>
                <TableCell>{t("options.contract")}</TableCell>
                <TableCell>{t("orders.side")}</TableCell>
                <TableCell align="right">{t("common.quantity")}</TableCell>
                <TableCell align="right">{t("orders.notional")}</TableCell>
                <TableCell>{t("common.type")}</TableCell>
                <TableCell>{t("common.status")}</TableCell>
                <TableCell>{t("orders.submitted")}</TableCell>
                <TableCell>{t("orders.filled")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {orders.map((o) => (
                <TableRow key={o.id}>
                  <TableCell>{o.symbol}</TableCell>
                  <TableCell>
                    {o.option_instrument ? (
                      <OptionInstrumentSummary instrument={o.option_instrument} dense />
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>{o.side === "buy" ? t("orderSide.buy") : t("orderSide.sell")}</TableCell>
                  <TableCell align="right">{o.quantity ?? "—"}</TableCell>
                  <TableCell align="right">{o.notional === null ? "—" : formatCurrency(locale, o.notional)}</TableCell>
                  <TableCell>{localizeValue(t, `orderType.${o.order_type.toLowerCase()}`, o.order_type)}</TableCell>
                  <TableCell>
                    <Chip label={localizeValue(t, `status.${o.status.toUpperCase()}`, o.status)} size="small" color={statusColor(o.status)} variant="outlined" />
                  </TableCell>
                  <TableCell>{o.submitted_at ? formatDateTime(locale, o.submitted_at) : "—"}</TableCell>
                  <TableCell>{o.filled_at ? formatDateTime(locale, o.filled_at) : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
            </Table>
          </>
        )}
      </Paper>
    </Box>
  );
}
