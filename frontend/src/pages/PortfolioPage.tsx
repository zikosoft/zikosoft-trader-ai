import { useMemo } from "react";
import { Alert, Box, Grid, Paper, Skeleton, Typography } from "@mui/material";
import { useLivePolling } from "../hooks/useLivePolling";
import { fetchPortfolioHistory, fetchPortfolioSummary } from "../api/portfolio";
import { ApiError, describeError } from "../api/client";
import { useThemeMode } from "../useThemeMode";
import { PerformanceCardsRow, PortfolioStatCards } from "./overview/PortfolioOverview";
import PositionsAllocation from "./overview/PositionsAllocation";
import PortfolioCurveChart from "./market/PortfolioCurveChart";
import { useI18n } from "../i18n/I18nContext";

// §écran dédié Portfolio (28/08 — fermeture des liens de menu B12-B18/B22/
// B25/B26/B31, voir AVANCEMENT.md) — jusqu'ici un `PlaceholderPage`
// pointant vers "Cartes livrées en B26 (Overview)". Les données et les
// composants existent déjà (B18 backend, B26/B27 frontend) : cet écran ne
// fait qu'assembler ce qui est déjà construit et déjà testé
// (`PortfolioStatCards`, `PerformanceCardsRow`, `PositionsAllocation`,
// `PortfolioCurveChart`) sur une route dédiée avec un historique complet
// (`GET /api/portfolio/history`, `limit=200`), au lieu de la fenêtre
// glissante utilisée par Overview/Market. Aucune nouvelle route backend,
// aucun nouveau composant de rendu.
export default function PortfolioPage() {
  const { t } = useI18n();
  const { mode } = useThemeMode();
  const { data: summary, error: summaryError, loading: summaryLoading } = useLivePolling(fetchPortfolioSummary, 5000);
  const { data: history, error: historyError } = useLivePolling(() => fetchPortfolioHistory(200), 30000);

  const chronological = useMemo(() => {
    if (!history) return [];
    return [...history.items].reverse().map((h) => ({ x: h.snapshot_at, y: h.portfolio_value }));
  }, [history]);

  if (summaryLoading && !summary && !summaryError) {
    return (
      <Box>
        <Skeleton variant="text" width={220} height={48} sx={{ mb: 2 }} />
        <Skeleton variant="rectangular" height={300} sx={{ borderRadius: 1 }} />
      </Box>
    );
  }

  // §même discipline que OverviewPage/ColdStartView — 404 tant que le
  // Portfolio Worker (B18) n'a pas encore fait un premier tour pour ce
  // contexte n'est pas une erreur à afficher en rouge, c'est un état
  // honnête "pas encore de données".
  if (!summary && summaryError instanceof ApiError && summaryError.code === "NOT_FOUND") {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.portfolio")}
        </Typography>
        <Alert severity="info">
          {t("portfolio.noPortfolioYet")}
        </Alert>
      </Box>
    );
  }

  if (!summary && summaryError) {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.portfolio")}
        </Typography>
        <Alert severity="error">{describeError(summaryError)}</Alert>
      </Box>
    );
  }

  if (!summary) return null;

  return (
    <Box>
      <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
        {t("navigation.portfolio")}
      </Typography>

      {summaryError !== null && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("common.showingLastKnownData", { error: describeError(summaryError) })}
        </Alert>
      )}

      <Box sx={{ mb: 3 }}>
        <PortfolioStatCards summary={summary} />
        <PerformanceCardsRow />
      </Box>

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid size={12}>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
              {t("portfolio.history")}
            </Typography>
            {historyError && !(historyError instanceof ApiError && historyError.code === "NOT_FOUND") ? (
              <Alert severity="warning">{describeError(historyError)}</Alert>
            ) : (
              <PortfolioCurveChart points={chronological} themeMode={mode} />
            )}
          </Paper>
        </Grid>
      </Grid>

      <PositionsAllocation portfolioValue={summary.portfolio_value} cash={summary.cash} />
    </Box>
  );
}
