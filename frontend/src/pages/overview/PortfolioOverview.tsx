import { Grid } from "@mui/material";
import { useLivePolling } from "../../hooks/useLivePolling";
import { fetchPerformanceCards, type PortfolioSummary } from "../../api/portfolio";
import StatCard from "../../components/StatCard";

// §B26 "Portfolio value/Cash/Buying power/Daily P&L/Total P&L" — cartes de
// synthèse à partir du résumé déjà chargé par `OverviewPage` (une seule
// lecture de `/api/portfolio/summary`, pas une par carte).

const CURRENCY = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function formatMoney(value: number | null): string {
  if (value === null) return "—";
  return CURRENCY.format(value);
}

function plColor(value: number | null): "success.main" | "error.main" | "text.primary" {
  if (value === null) return "text.primary";
  if (value > 0) return "success.main";
  if (value < 0) return "error.main";
  return "text.primary";
}

export function PortfolioStatCards({ summary }: { summary: PortfolioSummary }) {
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <StatCard label="Portfolio value" value={formatMoney(summary.portfolio_value)} />
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <StatCard label="Cash" value={formatMoney(summary.cash)} />
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <StatCard label="Buying power" value={formatMoney(summary.buying_power)} />
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        {/* §B18 anti-fabrication — `null` reste "—", jamais affiché comme 0 $. */}
        <StatCard label="Daily P&L" value={formatMoney(summary.daily_pl)} color={plColor(summary.daily_pl)} />
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <StatCard label="Total P&L" value={formatMoney(summary.total_pl)} color={plColor(summary.total_pl)} />
      </Grid>
    </Grid>
  );
}

// §B26 "Cartes 1D–7D" — même wording exact que le backend (§18 de la spec)
// quand une fenêtre n'est pas encore calculable, jamais une variation
// fabriquée (voir `backend/app/schemas/portfolio.py::PerformanceCardOut`).
export function PerformanceCardsRow() {
  const { data, error } = useLivePolling(fetchPerformanceCards, 5000);

  if (error || !data) return null;

  return (
    <Grid container spacing={2} sx={{ mt: 0.5 }}>
      {data.cards.map((card) => {
        const percent = card.percent_change ?? null;
        const value = card.available
          ? `${percent !== null && percent >= 0 ? "+" : ""}${percent !== null ? percent.toFixed(2) : "—"} % (${formatMoney(card.value_change ?? null)})`
          : (card.reason ?? "Not enough account history yet");
        return (
          <Grid key={card.window} size={{ xs: 12, sm: 4 }}>
            <StatCard label={card.window} value={value} color={card.available ? plColor(percent) : "text.primary"} />
          </Grid>
        );
      })}
    </Grid>
  );
}
