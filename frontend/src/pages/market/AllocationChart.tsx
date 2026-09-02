import { useMemo } from "react";
import { Box, Typography } from "@mui/material";
import type { EChartsOption } from "echarts";
import { useEchartsInstance } from "./useEchartsInstance";
import { useI18n } from "../../i18n/I18nContext";
import { formatCurrency } from "../../i18n/formatters";

// §B27 "Allocation" (ECharts) — remplace la version plate B26 (liste +
// LinearProgress, voir `pages/overview/PositionsAllocation.tsx`) par un vrai
// donut, calculé à partir des MÊMES données déjà chargées (positions/cash),
// aucune nouvelle route backend.
export default function AllocationChart({
  slices,
  themeMode,
}: {
  slices: { name: string; value: number }[];
  themeMode: "light" | "dark";
}) {
  const { locale, t } = useI18n();
  const option = useMemo<EChartsOption | null>(() => {
    const nonZero = slices.filter((s) => s.value > 0);
    if (nonZero.length === 0) return null;
    return {
      tooltip: {
        trigger: "item",
        formatter: (params: unknown) => {
          const item = params as { name: string; value: number; percent: number };
          return `${item.name}: ${formatCurrency(locale, item.value)} (${item.percent}%)`;
        },
      },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      series: [
        {
          type: "pie",
          radius: ["45%", "70%"],
          avoidLabelOverlap: true,
          itemStyle: { borderRadius: 4, borderWidth: 2 },
          label: { formatter: "{b}\n{d}%", fontSize: 11 },
          data: nonZero,
        },
      ],
    };
  }, [locale, slices]);

  const containerRef = useEchartsInstance(option, themeMode);

  // §bugfix B27 — voir `SparklineChart.tsx` : le conteneur `ref` doit
  // toujours être monté, jamais conditionnellement remplacé.
  return (
    <Box sx={{ position: "relative" }}>
      <Box ref={containerRef} sx={{ width: "100%", height: 260 }} />
      {!option && (
        <Typography
          color="text.secondary"
          sx={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          {t("charts.noAllocation")}
        </Typography>
      )}
    </Box>
  );
}
