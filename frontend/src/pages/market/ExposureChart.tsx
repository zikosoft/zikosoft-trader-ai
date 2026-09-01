import { useMemo } from "react";
import { Box, Typography } from "@mui/material";
import type { EChartsOption } from "echarts";
import { useEchartsInstance } from "./useEchartsInstance";

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
  const total = cash + invested;
  const option = useMemo<EChartsOption | null>(() => {
    if (total <= 0) return null;
    return {
      grid: { left: 8, right: 8, top: 8, bottom: 8 },
      xAxis: { type: "value", show: false, max: total },
      yAxis: { type: "category", show: false, data: ["exposition"] },
      tooltip: { trigger: "item", formatter: "{b}: ${c}" },
      series: [
        { name: "Investi", type: "bar", stack: "total", data: [invested], itemStyle: { color: "#42a5f5" }, barWidth: 28 },
        { name: "Cash", type: "bar", stack: "total", data: [cash], itemStyle: { color: "#90a4ae" }, barWidth: 28 },
      ],
    };
  }, [cash, invested, total]);

  const containerRef = useEchartsInstance(option, themeMode);

  // §bugfix B27 — voir `SparklineChart.tsx` : le conteneur `ref` doit
  // toujours être monté, jamais conditionnellement remplacé.
  const investedPct = total > 0 ? ((invested / total) * 100).toFixed(1) : null;
  return (
    <Box sx={{ position: "relative" }}>
      <Box ref={containerRef} sx={{ width: "100%", height: 60 }} />
      {investedPct === null ? (
        <Typography color="text.secondary" sx={{ py: 1 }}>
          Pas encore de portefeuille à ce jour.
        </Typography>
      ) : (
        <Typography variant="caption" color="text.secondary">
          {investedPct}% investi · {(100 - Number(investedPct)).toFixed(1)}% cash
        </Typography>
      )}
    </Box>
  );
}
