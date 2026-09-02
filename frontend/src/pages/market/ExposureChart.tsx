import { useMemo } from "react";
import { Box, Typography } from "@mui/material";
import type { EChartsOption } from "echarts";
import { useEchartsInstance } from "./useEchartsInstance";
import { useI18n } from "../../i18n/I18nContext";
import { formatCurrency, formatNumber } from "../../i18n/formatters";

// §B27 "Exposition" — barre empilée horizontale cash vs. investi, calculée
// depuis les MÊMES positions/cash déjà chargés par Overview/Market (aucune
// nouvelle route backend) : proportion réelle du portefeuille exposée au
// marché, pas une métrique de risque avancée (levier, delta, etc. — hors
// périmètre, ce projet ne trade qu'en actions au comptant, jamais de
// marge/short, voir §B32 "Paper mode forcé").
export default function ExposureChart({
  cash,
  invested,
  themeMode,
}: {
  cash: number;
  invested: number;
  themeMode: "light" | "dark";
}) {
  const { locale, t } = useI18n();
  const total = cash + invested;
  const option = useMemo<EChartsOption | null>(() => {
    if (total <= 0) return null;
    return {
      grid: { left: 8, right: 8, top: 8, bottom: 8 },
      xAxis: { type: "value", show: false, max: total },
      yAxis: { type: "category", show: false, data: ["exposition"] },
      tooltip: {
        trigger: "item",
        formatter: (params: unknown) => {
          const item = params as { seriesName: string; value: number };
          return `${item.seriesName}: ${formatCurrency(locale, item.value)}`;
        },
      },
      series: [
        { name: t("charts.invested"), type: "bar", stack: "total", data: [invested], itemStyle: { color: "#42a5f5" }, barWidth: 28 },
        { name: t("portfolioStats.cash"), type: "bar", stack: "total", data: [cash], itemStyle: { color: "#90a4ae" }, barWidth: 28 },
      ],
    };
  }, [cash, invested, locale, t, total]);

  const containerRef = useEchartsInstance(option, themeMode);

  // §bugfix B27 — voir `SparklineChart.tsx` : le conteneur `ref` doit
  // toujours être monté, jamais conditionnellement remplacé.
  const investedPct = total > 0 ? ((invested / total) * 100).toFixed(1) : null;
  return (
    <Box sx={{ position: "relative" }}>
      <Box ref={containerRef} sx={{ width: "100%", height: 60 }} />
      {investedPct === null ? (
        <Typography color="text.secondary" sx={{ py: 1 }}>
          {t("charts.noPortfolioToday")}
        </Typography>
      ) : (
        <Typography variant="caption" color="text.secondary">
          {t("charts.exposureSummary", {
            invested: formatNumber(locale, Number(investedPct), { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
            cash: formatNumber(locale, 100 - Number(investedPct), { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
          })}
        </Typography>
      )}
    </Box>
  );
}
