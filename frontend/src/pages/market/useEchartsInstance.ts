import { useEffect, useRef } from "react";
import * as echarts from "echarts";

// §B27 "Apache ECharts" — primitive partagée par tous les petits graphiques
// analytics (courbe portefeuille, sparklines, allocation, exposition,
// performance par stratégie) : une seule init/dispose/resize par graphique,
// jamais dupliquée. §B27 "Responsive resize" (ResizeObserver plutôt qu'un
// listener `window.resize` — correct même quand seul le conteneur change de
// taille, ex. redimensionnement d'un panneau latéral) ; §B27 "Cleanup des
// subscriptions" (`observer.disconnect()` + `chart.dispose()` au démontage) ;
// §B27 "Updates incrémentales" (`setOption` réutilise l'instance déjà créée,
// jamais un nouveau `echarts.init` par poll — voir l'appelant, qui ne
// rappelle `setOption` que lorsque `option` change réellement).
export function useEchartsInstance(option: echarts.EChartsOption | null, themeMode: "light" | "dark") {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  // §bugfix B27 — un changement de `themeMode` RECRÉE l'instance (voir
  // effet ci-dessous), mais l'effet `setOption` séparé ne se redéclenche
  // QUE quand `option` change de référence. Si `option` était déjà stable
  // (dernier poll inchangé) au moment du changement de thème, la nouvelle
  // instance restait vide (aucun `setOption` rejoué) — repéré en
  // vérification interactive (bascule dark/light avec des données déjà
  // chargées). `optionRef` porte toujours la dernière option connue,
  // rejouée immédiatement après CHAQUE (re)création de l'instance.
  const optionRef = useRef(option);
  optionRef.current = option;

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = echarts.init(containerRef.current, themeMode === "dark" ? "dark" : undefined);
    chartRef.current = chart;
    if (optionRef.current) chart.setOption(optionRef.current, { notMerge: false });

    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
    // Un changement de thème recrée l'instance (peu fréquent, clic
    // utilisateur) — plus simple et fiable que de retenter d'appliquer un
    // thème ECharts a posteriori sur une instance déjà initialisée.
  }, [themeMode]);

  useEffect(() => {
    if (!chartRef.current || !option) return;
    chartRef.current.setOption(option, { notMerge: false });
  }, [option]);

  return containerRef;
}
