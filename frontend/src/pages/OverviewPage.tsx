import { Alert, Box, Grid, Skeleton, Typography } from "@mui/material";
import { useOutletContext } from "react-router-dom";
import type { AppShellOutletContext } from "../AppShell";
import { useLivePolling } from "../hooks/useLivePolling";
import { fetchPortfolioSummary } from "../api/portfolio";
import { ApiError, describeError } from "../api/client";
import { PerformanceCardsRow, PortfolioStatCards } from "./overview/PortfolioOverview";
import PositionsAllocation from "./overview/PositionsAllocation";
import { AgentActivityCard, OrdersCard, RiskCard, StrategiesCard } from "./overview/ActivityWidgets";
import { AlertsWidgetCard, MarketWidgetCard, SystemHealthAndKillSwitchCard } from "./overview/StatusWidgets";
import ColdStartView from "./overview/ColdStartView";
import { useI18n } from "../i18n/I18nContext";

// §B26 "Dashboard principal" — dépend de B18 (portefeuille), B22 (santé
// système, via StatusWidgets), B25 (ce shell). B20 (notifications in-app)
// N'EST PAS livré : le widget "Alertes" reste donc un état vide honnête
// (voir StatusWidgets.tsx), même chose pour "Market chart" (B27) et l'
// action complète du "Kill switch" (B31, lecture seule ici) — voir
// AVANCEMENT.md pour la justification détaillée de chaque widget.
//
// Détection "sans activité" : `GET /api/portfolio/summary` répond 404
// NOT_FOUND tant que le Portfolio Worker n'a pas encore fait un premier
// tour pour ce contexte (voir B18) — c'est le signal RÉEL utilisé ici,
// jamais une portfolio_value à zéro qui prétendrait représenter un compte.
export default function OverviewPage() {
  const { t } = useI18n();
  const { contextState, onContextChanged } = useOutletContext<AppShellOutletContext>();
  const { data: summary, error, loading } = useLivePolling(fetchPortfolioSummary, 5000);

  // §D058/SystemHealthPage — même discipline "erreur transitoire n'efface
  // jamais la dernière donnée connue" : `summary` (posé par `useLivePolling`
  // uniquement sur un succès) reste affiché même si un poll ultérieur
  // échoue ; l'erreur s'affiche EN PLUS, jamais à la place.
  if (loading && !summary && !error) {
    return (
      <Box>
        <Skeleton variant="text" width={220} height={48} sx={{ mb: 2 }} />
        <Skeleton variant="rectangular" height={300} sx={{ borderRadius: 1 }} />
      </Box>
    );
  }

  // "Pas encore d'activité" ne s'affiche que tant qu'aucun résumé n'a
  // JAMAIS été chargé avec succès — un 404 après un premier succès est un
  // cas quasi impossible en opération réelle (le worker ne "désécrit"
  // jamais un snapshot) ; mieux vaut alors garder le dernier résumé connu
  // avec un bandeau d'erreur que de faire disparaître un vrai dashboard.
  if (!summary && error instanceof ApiError && error.code === "NOT_FOUND") {
    return <ColdStartView contextState={contextState} onContextChanged={onContextChanged} />;
  }

  if (!summary && error) {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.overview")}
        </Typography>
        <Alert severity="error">{describeError(error)}</Alert>
      </Box>
    );
  }

  if (!summary) return null;

  // §B26 "Dashboard sans activité" — un premier snapshot existe déjà
  // (sinon on serait dans la branche 404 ci-dessus) mais représente un
  // compte tout juste connecté : 100 % cash, aucune position n'a jamais
  // pu s'ouvrir tant que `cash === portfolio_value`. Signal RÉEL, dérivé
  // du résumé déjà chargé (aucune requête supplémentaire) — pas un
  // événement stocké séparément, juste une lecture honnête de l'état
  // actuel. Redirige vers la même vue que le cas 404, avec le VRAI résumé
  // en plus (`summary`) plutôt que de dupliquer son propre rendu.
  const noActivityYet = summary.cash === summary.portfolio_value && summary.daily_pl === null;
  if (noActivityYet) {
    return <ColdStartView contextState={contextState} onContextChanged={onContextChanged} summary={summary} />;
  }

  return (
    <Box>
      <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
        {t("navigation.overview")}
      </Typography>

      {error !== null && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("common.showingLastKnownData", { error: describeError(error) })}
        </Alert>
      )}

      <Box sx={{ mb: 3 }}>
        <PortfolioStatCards summary={summary} />
        <PerformanceCardsRow />
      </Box>

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <PositionsAllocation portfolioValue={summary.portfolio_value} cash={summary.cash} />
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Grid container spacing={2}>
            <Grid size={12}>
              <StrategiesCard />
            </Grid>
            <Grid size={12}>
              <OrdersCard />
            </Grid>
          </Grid>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <AgentActivityCard />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <RiskCard />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <SystemHealthAndKillSwitchCard />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <MarketWidgetCard />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <AlertsWidgetCard />
        </Grid>
      </Grid>
    </Box>
  );
}
