import { Grid } from "@mui/material";
import { useLivePolling } from "../../hooks/useLivePolling";
import { fetchPerformanceCards, type PortfolioSummary } from "../../api/portfolio";
import StatCard from "../../components/StatCard";
import { formatCurrency } from "../../i18n/formatters";
import { useI18n } from "../../i18n/I18nContext";

// §B26 "Portfolio value/Cash/Buying power/Daily P&L/Total P&L" — cartes de
// synthèse à partir du résumé déjà chargé par `OverviewPage` (une seule
// lecture de `/api/portfolio/summary`, pas une par carte).

function plColor(value: number | null): "success.main" | "error.main" | "text.primary" {
  if (value === null) return "text.primary";
  if (value > 0) return "success.main";
  if (value < 0) return "error.main";
  return "text.primary";
}

export function PortfolioStatCards({ summary }: { summary: PortfolioSummary }) {
  const { locale, t } = useI18n();
  const formatMoney = (value: number | null) => (value === null ? "—" : formatCurrency(locale, value));

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <StatCard label={t("portfolioStats.portfolioValue")} value={formatMoney(summary.portfolio_value)} />
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <StatCard label={t("portfolioStats.cash")} value={formatMoney(summary.cash)} />
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <StatCard label={t("portfolioStats.buyingPower")} value={formatMoney(summary.buying_power)} />
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        {/* §B18 anti-fabrication — `null` reste "—", jamais affiché comme 0 $. */}
        <StatCard label={t("portfolioStats.dailyPl")} value={formatMoney(summary.daily_pl)} color={plColor(summary.daily_pl)} />
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <StatCard label={t("portfolioStats.totalPl")} value={formatMoney(summary.total_pl)} color={plColor(summary.total_pl)} />
      </Grid>
    </Grid>
  );
}

// §B26 "Cartes 1D–7D" — même wording exact que le backend (§18 de la spec)
// quand une fenêtre n'est pas encore calculable, jamais une variation
// fabriquée (voir `backend/app/schemas/portfolio.py::PerformanceCardOut`).
export function PerformanceCardsRow() {
  const { locale, t } = useI18n();
  const { data, error } = useLivePolling(fetchPerformanceCards, 5000);
  const formatMoney = (value: number | null) => (value === null ? "—" : formatCurrency(locale, value));

  if (error || !data) return null;

  return (
    <Grid container spacing={2} sx={{ mt: 0.5 }}>
      {data.cards.map((card) => {
        const percent = card.percent_change ?? null;
        const value = card.available
          ? `${percent !== null && percent >= 0 ? "+" : ""}${percent !== null ? percent.toFixed(2) : "—"} % (${formatMoney(card.value_change ?? null)})`
          : (card.reason ?? t("portfolioStats.notEnoughHistory"));
        return (
          <Grid key={card.window} size={{ xs: 12, sm: 4 }}>
            <StatCard label={card.window} value={value} color={card.available ? plColor(percent) : "text.primary"} />
          </Grid>
        );
      })}
    </Grid>
  );
}
