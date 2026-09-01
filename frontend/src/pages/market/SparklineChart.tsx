import { useMemo } from "react";
import { Box } from "@mui/material";
import type { EChartsOption } from "echarts";
import { useEchartsInstance } from "./useEchartsInstance";

// §B27 "Sparklines 1D-7D" — mini courbe ECharts sans axes, réutilisée pour
// les fenêtres 1D/7D (données déjà chargées via `GET /api/portfolio/history`,
// aucune route dédiée). Réutilisée aussi par le widget "Market" du
// dashboard (StatusWidgets.tsx) pour un aperçu de prix.
export default function SparklineChart({
  points,
  color = "#42a5f5",
  height = 48,
  themeMode,
}: {
  points: { x: string; y: number }[];
  color?: string;
  height?: number;
  themeMode: "light" | "dark";
}) {
  const option = useMemo<EChartsOption | null>(() => {
    if (points.length === 0) return null;
    const up = points[points.length - 1].y >= points[0].y;
    const lineColor = up ? "#26a69a" : "#ef5350";
    return {
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: "category", show: false, data: points.map((p) => p.x) },
      yAxis: { type: "value", show: false, min: "dataMin", max: "dataMax" },
      series: [
        {
          type: "line",
          data: points.map((p) => p.y),
          showSymbol: false,
          lineStyle: { width: 1.5, color: color === "auto" ? lineColor : color },
          areaStyle: { opacity: 0.12, color: color === "auto" ? lineColor : color },
        },
      ],
      tooltip: { show: false },
      animation: false,
    };
  }, [points, color]);

  const containerRef = useEchartsInstance(option, themeMode);

  // §bugfix B27 — le conteneur `ref` doit TOUJOURS être monté, même quand
  // `points` est encore vide (premier rendu, avant que le poll parent
  // n'ait chargé de données) : `useEchartsInstance` crée le graphique une
  // seule fois au montage (voir son effet `[themeMode]`), donc omettre
  // conditionnellement ce `<Box>` au premier rendu empêchait `echarts.init`
  // de jamais s'exécuter, même une fois les données arrivées ensuite.
  return <Box ref={containerRef} sx={{ width: "100%", height }} />;
}
