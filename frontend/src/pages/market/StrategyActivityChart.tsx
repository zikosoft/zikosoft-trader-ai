import { useMemo } from "react";
import { Box, Typography } from "@mui/material";
import type { StrategyActivity } from "../../api/market";
import type { EChartsOption } from "echarts";
import { useEchartsInstance } from "./useEchartsInstance";
import { useI18n } from "../../i18n/I18nContext";

// §B27 "Performance par stratégie" — voir docstring de
// `backend/app/market.py::strategy_activity` pour la limite honnête
// assumée : Alpaca n'attribue aucun P&L par stratégie et ce projet ne tient
// pas de grand livre interne à ce jour. Ce graphique montre donc un PROXY
// réel — nombre d'ordres BUY/SELL et notional cumulé par stratégie active —
// jamais un P&L fabriqué.
export default function StrategyActivityChart({
  strategies,
  themeMode,
}: {
  strategies: StrategyActivity[];
  themeMode: "light" | "dark";
}) {
  const { t } = useI18n();
  const option = useMemo<EChartsOption | null>(() => {
    if (strategies.length === 0) return null;
    const names = strategies.map((s) => s.name);
    return {
      grid: { left: 120, right: 16, top: 16, bottom: 32 },
      xAxis: { type: "value", name: t("charts.orders") },
      yAxis: { type: "category", data: names, axisLabel: { fontSize: 11 } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { top: 0 },
      series: [
        { name: t("signal.BUY"), type: "bar", stack: "orders", data: strategies.map((s) => s.buy_count), itemStyle: { color: "#26a69a" } },
        { name: t("signal.SELL"), type: "bar", stack: "orders", data: strategies.map((s) => s.sell_count), itemStyle: { color: "#ef5350" } },
      ],
    };
  }, [strategies, t]);

  const containerRef = useEchartsInstance(option, themeMode);

  // §bugfix B27 — voir `SparklineChart.tsx` : le conteneur `ref` doit
  // toujours être monté, jamais conditionnellement remplacé.
  return (
    <Box sx={{ position: "relative" }}>
      <Box ref={containerRef} sx={{ width: "100%", height: Math.max(120, strategies.length * 48) }} />
      {!option && (
        <Typography
          color="text.secondary"
          sx={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          {t("charts.noStrategyActivity")}
        </Typography>
      )}
    </Box>
  );
}
