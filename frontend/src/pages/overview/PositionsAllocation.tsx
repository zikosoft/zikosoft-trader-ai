import { Box, Paper, Skeleton, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { useLivePolling } from "../../hooks/useLivePolling";
import { fetchPositions } from "../../api/portfolio";
import { useThemeMode } from "../../useThemeMode";
import AllocationChart from "../market/AllocationChart";

const CURRENCY = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function formatMoney(value: number | null): string {
  return value === null ? "—" : CURRENCY.format(value);
}

// §B26 "Positions ouvertes" (table) — §B27 "Allocation" (ECharts, remplace
// la version plate B26 liste + LinearProgress) : répartition calculée à
// partir des VRAIES positions (`market_value`) et du cash réel déjà chargé
// par `OverviewPage` — aucune nouvelle route backend, aucune donnée
// fabriquée.
export default function PositionsAllocation({ portfolioValue, cash }: { portfolioValue: number; cash: number }) {
  const { data, loading } = useLivePolling(fetchPositions, 5000);
  const { mode } = useThemeMode();

  if (loading && !data) {
    return <Skeleton variant="rectangular" height={220} sx={{ borderRadius: 1 }} />;
  }

  const positions = data?.positions ?? [];

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
          Positions ouvertes
        </Typography>
        {positions.length === 0 ? (
          <Typography color="text.secondary">Aucune position ouverte pour le moment.</Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Symbole</TableCell>
                <TableCell align="right">Quantité</TableCell>
                <TableCell align="right">Prix moyen</TableCell>
                <TableCell align="right">Valeur marché</TableCell>
                <TableCell align="right">P&L latent</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {positions.map((p) => (
                <TableRow key={p.symbol}>
                  <TableCell>{p.symbol}</TableCell>
                  <TableCell align="right">{p.quantity}</TableCell>
                  <TableCell align="right">{formatMoney(p.average_entry_price)}</TableCell>
                  <TableCell align="right">{formatMoney(p.market_value)}</TableCell>
                  <TableCell
                    align="right"
                    sx={{
                      color:
                        p.unrealized_pl === null
                          ? "text.primary"
                          : p.unrealized_pl > 0
                            ? "success.main"
                            : p.unrealized_pl < 0
                              ? "error.main"
                              : "text.primary",
                    }}
                  >
                    {formatMoney(p.unrealized_pl)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
          Allocation
        </Typography>
        {portfolioValue <= 0 ? (
          <Typography color="text.secondary">Pas encore de données de portefeuille.</Typography>
        ) : (
          <AllocationChart
            themeMode={mode}
            slices={[
              ...positions.map((p) => ({ name: p.symbol, value: p.market_value ?? 0 })),
              { name: "Cash", value: cash },
            ]}
          />
        )}
      </Paper>
    </Box>
  );
}
