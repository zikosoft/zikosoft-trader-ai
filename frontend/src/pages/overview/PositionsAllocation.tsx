import { Box, Paper, Skeleton, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { useLivePolling } from "../../hooks/useLivePolling";
import { fetchPositions } from "../../api/portfolio";
import { useThemeMode } from "../../useThemeMode";
import AllocationChart from "../market/AllocationChart";
import { formatCurrency } from "../../i18n/formatters";
import { useI18n } from "../../i18n/I18nContext";

// §B26 "Positions ouvertes" (table) — §B27 "Allocation" (ECharts, remplace
// la version plate B26 liste + LinearProgress) : répartition calculée à
// partir des VRAIES positions (`market_value`) et du cash réel déjà chargé
// par `OverviewPage` — aucune nouvelle route backend, aucune donnée
// fabriquée.
export default function PositionsAllocation({ portfolioValue, cash }: { portfolioValue: number; cash: number }) {
  const { locale, t } = useI18n();
  const { data, loading } = useLivePolling(fetchPositions, 5000);
  const { mode } = useThemeMode();
  const formatMoney = (value: number | null) => (value === null ? "—" : formatCurrency(locale, value));

  if (loading && !data) {
    return <Skeleton variant="rectangular" height={220} sx={{ borderRadius: 1 }} />;
  }

  const positions = data?.positions ?? [];

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
          {t("positions.title")}
        </Typography>
        {positions.length === 0 ? (
          <Typography color="text.secondary">{t("positions.empty")}</Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("common.symbol")}</TableCell>
                <TableCell align="right">{t("common.quantity")}</TableCell>
                <TableCell align="right">{t("positions.averagePrice")}</TableCell>
                <TableCell align="right">{t("positions.marketValue")}</TableCell>
                <TableCell align="right">{t("positions.unrealizedPl")}</TableCell>
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
          {t("positions.allocation")}
        </Typography>
        {portfolioValue <= 0 ? (
          <Typography color="text.secondary">{t("positions.noPortfolioData")}</Typography>
        ) : (
          <AllocationChart
            themeMode={mode}
            slices={[
              ...positions.map((p) => ({ name: p.symbol, value: p.market_value ?? 0 })),
              { name: t("portfolioStats.cash"), value: cash },
            ]}
          />
        )}
      </Paper>
    </Box>
  );
}
