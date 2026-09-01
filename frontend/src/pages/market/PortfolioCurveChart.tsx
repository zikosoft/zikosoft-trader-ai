import { useMemo } from "react";
import { Box, Typography } from "@mui/material";
import type { EChartsOption } from "echarts";
import { useEchartsInstance } from "./useEchartsInstance";

// §B27 "Courbe portefeuille" — ECharts, alimentée par
// `GET /api/portfolio/history` (B18, déjà construite), aucune nouvelle
// route backend nécessaire.
export default function PortfolioCurveChart({
  points,
  themeMode,
}: {
  points: { x: string; y: number }[];
  themeMode: "light" | "dark";
}) {
  const option = useMemo<EChartsOption | null>(() => {
    if (points.length === 0) return null;
    return {
      grid: { left: 56, right: 16, top: 16, bottom: 32 },
      xAxis: {
        type: "category",
        data: points.map((p) => p.x),
        axisLabel: { formatter: (v: string) => new Date(v).toLocaleDateString() },
      },
      yAxis: { type: "value", scale: true, axisLabel: { formatter: (v: number) => `$${v.toLocaleString()}` } },
      tooltip: {
        trigger: "axis",
        formatter: (params: unknown) => {
          const p = (params as { value: number; axisValue: string }[])[0];
          return `${new Date(p.axisValue).toLocaleString()}<br/>$${p.value.toLocaleString()}`;
        },
      },
      series: [
        {
          type: "line",
          data: points.map((p) => p.y),
          showSymbol: false,
          smooth: true,
          lineStyle: { width: 2, color: "#42a5f5" },
          areaStyle: { opacity: 0.08, color: "#42a5f5" },
        },
      ],
    };
  }, [points]);

  const containerRef = useEchartsInstance(option, themeMode);

  // §bugfix B27 — le conteneur `ref` doit TOUJOURS être monté (voir
  // `SparklineChart.tsx` pour l'explication complète) : ne jamais le
  // remplacer conditionnellement par le message "pas encore assez
  // d'historique", seulement le superposer par-dessus.
  return (
    <Box sx={{ position: "relative" }}>
      <Box ref={containerRef} sx={{ width: "100%", height: 280 }} />
      {points.length === 0 && (
        <Typography
          color="text.secondary"
          sx={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", px: 2 }}
        >
          Pas encore assez d'historique de portefeuille pour tracer une courbe.
        </Typography>
      )}
    </Box>
  );
}
