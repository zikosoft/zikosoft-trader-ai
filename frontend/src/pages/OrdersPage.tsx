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
import { fetchRecentOrders, type RecentOrder } from "../api/orders";
import { ApiError, describeError } from "../api/client";

// §écran dédié Orders (28/08 — fermeture des liens de menu, voir
// AVANCEMENT.md) — remplace le `PlaceholderPage` qui pointait vers le
// widget dashboard "Ordres récents" (B26). Route déjà servie par le
// backend depuis B17/B26 (`GET /api/orders/recent`) : cet écran ne fait
// qu'afficher les MAX_RECENT_LIMIT=50 dernières lignes en table complète
// au lieu des 5 lignes condensées du widget — aucune nouvelle route
// backend. La pagination réelle au-delà de 50 lignes reste un gap honnête
// (voir `backend/app/routers/orders.py`, docstring d'origine) : documenté
// dans AVANCEMENT.md plutôt que masqué.

const CURRENCY = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function formatMoney(value: number | null): string {
  return value === null ? "—" : CURRENCY.format(value);
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fr-FR");
}

function statusColor(status: string): "success" | "error" | "warning" | "default" {
  const s = status.toLowerCase();
  if (s === "filled") return "success";
  if (s === "canceled" || s === "cancelled" || s === "rejected" || s === "expired") return "error";
  if (s === "pending_new" || s === "new" || s === "accepted" || s === "partially_filled") return "warning";
  return "default";
}

function sideLabel(side: RecentOrder["side"]): string {
  return side === "buy" ? "Achat" : "Vente";
}

export default function OrdersPage() {
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
          Orders
        </Typography>
        <Alert severity="info">Aucun contexte d'exécution actif — choisis d'abord un contexte (Paper ou Replay).</Alert>
      </Box>
    );
  }

  if (!data && error) {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          Orders
        </Typography>
        <Alert severity="error">{describeError(error)}</Alert>
      </Box>
    );
  }

  const orders = data?.orders ?? [];

  return (
    <Box>
      <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
        Orders
      </Typography>

      {error !== null && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {describeError(error)} — dernières données connues affichées ci-dessous.
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 2 }}>
        {orders.length === 0 ? (
          <Typography color="text.secondary">Aucun ordre pour le moment.</Typography>
        ) : (
          <>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Les {orders.length} ordre{orders.length > 1 ? "s" : ""} les plus récents de ce contexte (maximum 50 —
              pagination complète non livrée, voir AVANCEMENT.md).
            </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Symbole</TableCell>
                <TableCell>Sens</TableCell>
                <TableCell align="right">Quantité</TableCell>
                <TableCell align="right">Notionnel</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Statut</TableCell>
                <TableCell>Soumis</TableCell>
                <TableCell>Exécuté</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {orders.map((o) => (
                <TableRow key={o.id}>
                  <TableCell>{o.symbol}</TableCell>
                  <TableCell>{sideLabel(o.side)}</TableCell>
                  <TableCell align="right">{o.quantity ?? "—"}</TableCell>
                  <TableCell align="right">{formatMoney(o.notional)}</TableCell>
                  <TableCell>{o.order_type}</TableCell>
                  <TableCell>
                    <Chip label={o.status} size="small" color={statusColor(o.status)} variant="outlined" />
                  </TableCell>
                  <TableCell>{formatDate(o.submitted_at)}</TableCell>
                  <TableCell>{formatDate(o.filled_at)}</TableCell>
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
