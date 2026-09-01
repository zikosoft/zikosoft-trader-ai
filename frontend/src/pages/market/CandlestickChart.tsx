import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { Box, Typography } from "@mui/material";
import type { Bar, DecisionMarkersResponse, OrderMarker } from "../../api/market";

// §B27 "Graphiques marché et analytics" — TradingView Lightweight Charts.
// Bibliothèque npm open-source (MIT), embarquée localement (§B27
// "Aucune clé/compte TradingView" — contrairement au widget hébergé
// TradingView, cette librairie ne parle à AUCUN serveur externe, aucune
// clé/compte n'est nécessaire ni possible). §B27 "Attribution TradingView"
// — logo/lien requis par la licence, voir le pied de page sous le
// graphique dans `MarketPage.tsx`.

export type MarkerClickPayload =
  | { kind: "order"; order: OrderMarker }
  | { kind: "proposal"; proposal: DecisionMarkersResponse["proposals"][number] }
  | { kind: "risk_event"; riskEvent: DecisionMarkersResponse["risk_events"][number] };

function toUnixTime(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

// §B27 "Moyennes mobiles" — calcul déterministe côté client à partir des
// mêmes bougies déjà affichées (aucune route backend dédiée nécessaire,
// même principe que `moving_average_crossover` côté stratégie, B12, mais
// ici purement pour l'affichage).
function simpleMovingAverage(bars: Bar[], period: number): { time: UTCTimestamp; value: number }[] {
  if (bars.length < period) return [];
  const out: { time: UTCTimestamp; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i - period].close;
    if (i >= period - 1) {
      out.push({ time: toUnixTime(bars[i].bar_at), value: sum / period });
    }
  }
  return out;
}

export default function CandlestickChart({
  bars,
  orders,
  decisions,
  themeMode,
  showMovingAverages,
  onMarkerClick,
}: {
  bars: Bar[];
  orders: OrderMarker[];
  decisions: DecisionMarkersResponse | null;
  themeMode: "light" | "dark";
  showMovingAverages: boolean;
  onMarkerClick: (payload: MarkerClickPayload) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ma50SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  // Ref plutôt que state — évite de reconstruire le callback `subscribeClick`
  // (donc de re-souscrire) à chaque changement de marqueurs (§B27
  // "Aucun rerender global inutile").
  const markerLookupRef = useRef<Map<number, MarkerClickPayload>>(new Map());
  const onMarkerClickRef = useRef(onMarkerClick);
  onMarkerClickRef.current = onMarkerClick;
  // Lignes de prix stop-loss/take-profit actuellement affichées — suivies
  // hors effet pour pouvoir être nettoyées aussi bien par l'effet marqueurs
  // que par la (re)création du graphique (voir `applyMarkers` ci-dessous).
  const priceLinesRef = useRef<ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]>([]);

  // §bugfix B27 — un changement de `themeMode` RECRÉE le graphique (voir
  // effet de création ci-dessous), mais les deux effets séparés `setData`/
  // marqueurs ne se redéclenchent QUE quand `bars`/`orders`/`decisions`
  // changent de référence. Si ces données étaient déjà stables (dernier
  // poll inchangé) au moment du changement de thème, le nouveau graphique
  // restait vide — repéré en vérification interactive (bascule dark/light
  // avec des données déjà chargées, même bug que `useEchartsInstance.ts`).
  // Ces refs portent toujours les dernières valeurs connues, rejouées
  // immédiatement après CHAQUE (re)création du graphique.
  const barsRef = useRef(bars);
  barsRef.current = bars;
  const showMovingAveragesRef = useRef(showMovingAverages);
  showMovingAveragesRef.current = showMovingAverages;
  const ordersRef = useRef(orders);
  ordersRef.current = orders;
  const decisionsRef = useRef(decisions);
  decisionsRef.current = decisions;

  // Applique les bougies/volume/MA sur des séries déjà créées — appelée à
  // la fois par l'effet `setData` (poll normal) et juste après la
  // (re)création du graphique (bascule de thème).
  function applyBars(
    candleSeries: ISeriesApi<"Candlestick">,
    volumeSeries: ISeriesApi<"Histogram">,
    ma20Series: ISeriesApi<"Line">,
    ma50Series: ISeriesApi<"Line">,
    barsData: Bar[],
    showMA: boolean,
  ) {
    const candleData = barsData.map((b) => ({
      time: toUnixTime(b.bar_at),
      open: b.open ?? b.close,
      high: b.high ?? b.close,
      low: b.low ?? b.close,
      close: b.close,
    }));
    candleSeries.setData(candleData);
    volumeSeries.setData(
      barsData.map((b) => ({
        time: toUnixTime(b.bar_at),
        value: b.volume ?? 0,
        color: (b.high ?? b.close) >= (b.open ?? b.close) ? "#26a69a80" : "#ef535080",
      })),
    );
    if (showMA) {
      ma20Series.setData(simpleMovingAverage(barsData, 20));
      ma50Series.setData(simpleMovingAverage(barsData, 50));
    } else {
      ma20Series.setData([]);
      ma50Series.setData([]);
    }
  }

  // Applique marqueurs BUY/SELL/Proposition IA/Rejet + lignes de prix
  // stop-loss/take-profit sur une série déjà créée — même raison d'être
  // que `applyBars` ci-dessus. Nettoie toujours les anciennes lignes de
  // prix (`priceLinesRef`) avant d'en recréer, qu'elle soit appelée par
  // l'effet marqueurs (poll normal) ou juste après (re)création du
  // graphique.
  function applyMarkers(
    candleSeries: ISeriesApi<"Candlestick">,
    ordersData: OrderMarker[],
    decisionsData: DecisionMarkersResponse | null,
  ) {
    const lookup = new Map<number, MarkerClickPayload>();
    const markers: SeriesMarker<Time>[] = [];

    for (const order of ordersData) {
      const at = order.filled_at ?? order.submitted_at;
      if (!at || order.status !== "filled") continue;
      const time = toUnixTime(at);
      const isBuy = order.side === "buy";
      markers.push({
        time,
        position: isBuy ? "belowBar" : "aboveBar",
        color: isBuy ? "#26a69a" : "#ef5350",
        shape: isBuy ? "arrowUp" : "arrowDown",
        text: isBuy ? "BUY" : "SELL",
      });
      lookup.set(time, { kind: "order", order });
    }

    if (decisionsData) {
      for (const proposal of decisionsData.proposals) {
        if (!proposal.market_data_timestamp) continue;
        const time = toUnixTime(proposal.market_data_timestamp);
        markers.push({
          time,
          position: "inBar",
          color: "#42a5f5",
          shape: "circle",
          text: `IA:${proposal.outcome}`,
        });
        lookup.set(time, { kind: "proposal", proposal });
      }
      for (const riskEvent of decisionsData.risk_events) {
        if (!riskEvent.market_data_timestamp || riskEvent.outcome !== "REJECTED") continue;
        const time = toUnixTime(riskEvent.market_data_timestamp);
        markers.push({
          time,
          position: "aboveBar",
          color: "#fb8c00",
          shape: "square",
          text: "REJECTED",
        });
        lookup.set(time, { kind: "risk_event", riskEvent });
      }
    }

    markers.sort((a, b) => (a.time as number) - (b.time as number));
    markerLookupRef.current = lookup;
    createSeriesMarkers(candleSeries, markers);

    // Niveaux stop-loss/take-profit — lignes de prix horizontales, pas des
    // marqueurs temporels (un stop-loss ne "se produit" pas à un instant
    // précis tant qu'il n'est pas déclenché).
    for (const line of priceLinesRef.current) candleSeries.removePriceLine(line);
    priceLinesRef.current = [];
    const seenLevels = new Set<string>();
    for (const order of ordersData) {
      // §B27 — forme réelle écrite par `workers/order_worker/main.py`
      // (`_build_bracket_legs`) : `{"stop_loss_pct": ..., "leg":
      // {"stop_price": ...}}` (idem take_profit/`limit_price`) ; `leg` peut
      // être absent (ordre bloqué avant Alpaca, aucune jambe calculée) —
      // jamais fabriqué à partir du seul pourcentage dans ce cas.
      const slLeg = order.stop_loss?.leg as { stop_price?: number } | null | undefined;
      const tpLeg = order.take_profit?.leg as { limit_price?: number } | null | undefined;
      const slPrice = typeof slLeg?.stop_price === "number" ? slLeg.stop_price : null;
      const tpPrice = typeof tpLeg?.limit_price === "number" ? tpLeg.limit_price : null;
      if (slPrice !== null && !seenLevels.has(`sl:${slPrice}`)) {
        seenLevels.add(`sl:${slPrice}`);
        priceLinesRef.current.push(
          candleSeries.createPriceLine({ price: slPrice, color: "#ef5350", lineStyle: 2, title: "Stop-loss", lineWidth: 1 }),
        );
      }
      if (tpPrice !== null && !seenLevels.has(`tp:${tpPrice}`)) {
        seenLevels.add(`tp:${tpPrice}`);
        priceLinesRef.current.push(
          candleSeries.createPriceLine({ price: tpPrice, color: "#26a69a", lineStyle: 2, title: "Take-profit", lineWidth: 1 }),
        );
      }
    }
  }

  // Création du graphique une seule fois par montage — §B27 "Cleanup des
  // subscriptions" : `chart.remove()` au démontage libère le canvas et
  // désabonne le listener de clic, jamais de fuite entre navigations.
  useEffect(() => {
    if (!containerRef.current) return;
    const isDark = themeMode === "dark";
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: isDark ? "#e0e0e0" : "#1a1a1a",
      },
      grid: {
        vertLines: { color: isDark ? "#2a2a2a" : "#eeeeee" },
        horzLines: { color: isDark ? "#2a2a2a" : "#eeeeee" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });
    candleSeriesRef.current = candleSeries;

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: isDark ? "#546e7a" : "#90a4ae",
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volumeSeriesRef.current = volumeSeries;

    candleSeries.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.25 } });

    const ma20Series = chart.addSeries(LineSeries, {
      color: "#f5a623",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    ma20SeriesRef.current = ma20Series;
    const ma50Series = chart.addSeries(LineSeries, {
      color: "#7e57c2",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    ma50SeriesRef.current = ma50Series;

    // §bugfix B27 — rejoue immédiatement les dernières données connues
    // (refs) sur les séries fraîchement créées, sans attendre que les
    // effets `setData`/marqueurs se redéclenchent (leurs dépendances
    // n'ont pas forcément changé de référence lors d'un simple changement
    // de thème). `priceLinesRef` est réinitialisée car les lignes de prix
    // de l'ancien graphique n'existent plus (chart déjà détruit).
    priceLinesRef.current = [];
    applyBars(candleSeries, volumeSeries, ma20Series, ma50Series, barsRef.current, showMovingAveragesRef.current);
    applyMarkers(candleSeries, ordersRef.current, decisionsRef.current);
    chart.timeScale().fitContent();

    const clickHandler = (param: { time?: Time }) => {
      if (param.time === undefined) return;
      const payload = markerLookupRef.current.get(param.time as number);
      if (payload) onMarkerClickRef.current(payload);
    };
    chart.subscribeClick(clickHandler);

    return () => {
      chart.unsubscribeClick(clickHandler);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      ma20SeriesRef.current = null;
      ma50SeriesRef.current = null;
    };
    // Le thème n'est appliqué qu'à la (re)création — un changement de thème
    // recrée le graphique (peu fréquent, un clic utilisateur), pas de coût
    // de complexité supplémentaire pour un cas rare.
  }, [themeMode]);

  // §B27 "Updates incrémentales" — `setData` remplace le contenu d'une
  // série SANS recréer le graphique (canvas/listeners déjà en place, voir
  // effet ci-dessus) : seul ce `useEffect`-ci se redéclenche à chaque
  // poll de nouvelles bougies, jamais `createChart`.
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !ma20SeriesRef.current || !ma50SeriesRef.current) return;
    applyBars(candleSeriesRef.current, volumeSeriesRef.current, ma20SeriesRef.current, ma50SeriesRef.current, bars, showMovingAverages);
    chartRef.current?.timeScale().fitContent();
  }, [bars, showMovingAverages]);

  // Marqueurs BUY/SELL (ordres réellement exécutés) + Proposition IA +
  // Rejet Risk Engine + niveaux stop-loss/take-profit (§B27).
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    applyMarkers(candleSeriesRef.current, orders, decisions);
  }, [orders, decisions]);

  return (
    <Box>
      <Box ref={containerRef} sx={{ width: "100%", height: 420 }} />
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
        Charts by{" "}
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
          TradingView
        </a>{" "}
        (Lightweight Charts™) — aucune clé ni compte TradingView requis.
      </Typography>
    </Box>
  );
}
