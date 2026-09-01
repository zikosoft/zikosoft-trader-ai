import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  FormControlLabel,
  Grid,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Switch,
  Typography,
} from "@mui/material";
import { useLivePolling } from "../hooks/useLivePolling";
import { useThemeMode } from "../useThemeMode";
import {
  fetchBars,
  fetchDecisionMarkers,
  fetchOrderMarkers,
  fetchQuote,
  fetchStrategyActivity,
  fetchSymbols,
} from "../api/market";
import { fetchPortfolioHistory, fetchPositions, fetchPortfolioSummary } from "../api/portfolio";
import { ApiError, describeError } from "../api/client";
import CandlestickChart, { type MarkerClickPayload } from "./market/CandlestickChart";
import DecisionDetailsDialog from "./market/DecisionDetailsDialog";
import PortfolioCurveChart from "./market/PortfolioCurveChart";
import SparklineChart from "./market/SparklineChart";
import AllocationChart from "./market/AllocationChart";
import ExposureChart from "./market/ExposureChart";
import StrategyActivityChart from "./market/StrategyActivityChart";

// §B27 "Graphiques marché et analytics" — orchestrateur. Deux sections
// indépendantes, chacune propriétaire de son propre poll (§D058/D060, même
// discipline que `OverviewPage`/`pages/overview/*`, B26) :
//   1. Graphique chandelier (symbole sélectionné) — bougies réellement
//      persistées par le Market Agent (B10, voir B27 dans AVANCEMENT.md
//      pour pourquoi cette persistance a été ajoutée maintenant), marqueurs
//      BUY/SELL/stop-loss/take-profit (ordres B17) et Proposition IA/Rejet
//      Risk Engine (B13-B15).
//   2. Analytics compte — courbe portefeuille/sparklines/allocation/
//      exposition/performance par stratégie (B18/B12, aucune route
//      nouvelle sauf `strategy-activity`).
export default function MarketPage() {
  const { mode } = useThemeMode();
  const { data: symbols, loading: symbolsLoading } = useLivePolling(fetchSymbols, 30000);
  const [symbol, setSymbol] = useState<string | null>(null);
  const [showMA, setShowMA] = useState(true);
  const [clickedMarker, setClickedMarker] = useState<MarkerClickPayload | null>(null);

  useEffect(() => {
    if (symbol === null && symbols && symbols.length > 0) setSymbol(symbols[0]);
    if (symbol !== null && symbols && !symbols.includes(symbol)) setSymbol(symbols[0] ?? null);
  }, [symbols, symbol]);

  return (
    <Box>
      <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
        Market
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        {symbolsLoading && !symbols ? (
          <Skeleton variant="rectangular" height={420} sx={{ borderRadius: 1 }} />
        ) : !symbols || symbols.length === 0 ? (
          <Alert severity="info">
            Aucune donnée de marché disponible pour l'instant — le Market Agent (B10) n'a pas encore collecté de
            bougies pour un symbole surveillé. Ce graphique s'activera dès la première bougie réellement persistée.
          </Alert>
        ) : (
          <>
            <Box sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 2, mb: 1 }}>
              <Select size="small" value={symbol ?? ""} onChange={(e) => setSymbol(e.target.value)}>
                {symbols.map((s) => (
                  <MenuItem key={s} value={s}>
                    {s}
                  </MenuItem>
                ))}
              </Select>
              <QuoteBadge symbol={symbol} />
              <FormControlLabel
                control={<Switch size="small" checked={showMA} onChange={(e) => setShowMA(e.target.checked)} />}
                label="Moyennes mobiles (20/50)"
              />
            </Box>
            {symbol && <SymbolChart symbol={symbol} showMA={showMA} onMarkerClick={setClickedMarker} />}
          </>
        )}
      </Paper>

      <Typography variant="h5" component="h2" sx={{ mb: 2 }}>
        Analytics
      </Typography>
      <AnalyticsSection themeMode={mode} />

      <DecisionDetailsDialog payload={clickedMarker} onClose={() => setClickedMarker(null)} />
    </Box>
  );
}

function QuoteBadge({ symbol }: { symbol: string | null }) {
  const { data } = useLivePolling(async () => (symbol ? fetchQuote(symbol) : null), 15000);
  if (!symbol || !data) return null;
  return (
    <Typography variant="body1">
      <strong>{data.price.toFixed(2)} $</strong>
      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
        {data.as_of ? `au ${new Date(data.as_of).toLocaleString()}` : "horodatage source non disponible"}
      </Typography>
    </Typography>
  );
}

function SymbolChart({
  symbol,
  showMA,
  onMarkerClick,
}: {
  symbol: string;
  showMA: boolean;
  onMarkerClick: (p: MarkerClickPayload) => void;
}) {
  const { mode } = useThemeMode();
  const { data: barsData, loading: barsLoading } = useLivePolling(() => fetchBars(symbol, "1Day", 200), 15000);
  const { data: orders } = useLivePolling(() => fetchOrderMarkers(symbol, 100), 15000);
  const { data: decisions } = useLivePolling(() => fetchDecisionMarkers(symbol, 50), 15000);

  if (barsLoading && !barsData) return <Skeleton variant="rectangular" height={420} sx={{ borderRadius: 1 }} />;
  if (!barsData || barsData.bars.length === 0) {
    return (
      <Alert severity="info">
        Aucune bougie persistée pour {symbol} pour l'instant.
      </Alert>
    );
  }

  return (
    <CandlestickChart
      bars={barsData.bars}
      orders={orders?.orders ?? []}
      decisions={decisions ?? null}
      themeMode={mode}
      showMovingAverages={showMA}
      onMarkerClick={onMarkerClick}
    />
  );
}

function AnalyticsSection({ themeMode }: { themeMode: "light" | "dark" }) {
  const { data: history, error: historyError } = useLivePolling(() => fetchPortfolioHistory(200), 30000);
  const { data: positions } = useLivePolling(fetchPositions, 30000);
  const { data: summary } = useLivePolling(fetchPortfolioSummary, 30000);
  const { data: strategyActivity } = useLivePolling(fetchStrategyActivity, 30000);

  const chronological = useMemo(() => {
    if (!history) return [];
    return [...history.items].reverse().map((h) => ({ x: h.snapshot_at, y: h.portfolio_value }));
  }, [history]);

  const last1d = useMemo(() => sliceLastDays(chronological, 1), [chronological]);
  const last7d = useMemo(() => sliceLastDays(chronological, 7), [chronological]);

  const cash = summary?.cash ?? 0;
  const invested = (positions?.positions ?? []).reduce((sum, p) => sum + (p.market_value ?? 0), 0);

  if (historyError && historyError instanceof ApiError && historyError.code === "NOT_FOUND") {
    return (
      <Alert severity="info">
        Pas encore de portefeuille pour ce contexte — l'analytics se remplira dès le premier snapshot du Portfolio
        Worker (B18).
      </Alert>
    );
  }
  if (historyError && !(historyError instanceof ApiError && historyError.code === "VALIDATION_ERROR")) {
    return <Alert severity="warning">{describeError(historyError)}</Alert>;
  }

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, lg: 8 }}>
        <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
          <Typography variant="h6" component="h3" sx={{ mb: 1 }}>
            Courbe portefeuille
          </Typography>
          <PortfolioCurveChart points={chronological} themeMode={themeMode} />
        </Paper>
      </Grid>
      <Grid size={{ xs: 12, lg: 4 }}>
        <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
          <Typography variant="h6" component="h3" sx={{ mb: 1 }}>
            Sparklines
          </Typography>
          <Typography variant="caption" color="text.secondary">
            1D
          </Typography>
          <SparklineChart points={last1d} color="auto" themeMode={themeMode} height={56} />
          <Typography variant="caption" color="text.secondary">
            7D
          </Typography>
          <SparklineChart points={last7d} color="auto" themeMode={themeMode} height={56} />
        </Paper>
      </Grid>

      <Grid size={{ xs: 12, sm: 6, lg: 4 }}>
        <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
          <Typography variant="h6" component="h3" sx={{ mb: 1 }}>
            Allocation
          </Typography>
          <AllocationChart
            themeMode={themeMode}
            slices={[
              ...(positions?.positions ?? []).map((p) => ({ name: p.symbol, value: p.market_value ?? 0 })),
              { name: "Cash", value: cash },
            ]}
          />
        </Paper>
      </Grid>
      <Grid size={{ xs: 12, sm: 6, lg: 4 }}>
        <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
          <Typography variant="h6" component="h3" sx={{ mb: 1 }}>
            Exposition
          </Typography>
          <ExposureChart cash={cash} invested={invested} themeMode={themeMode} />
        </Paper>
      </Grid>
      <Grid size={{ xs: 12, lg: 4 }}>
        <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
          <Typography variant="h6" component="h3" sx={{ mb: 1 }}>
            Performance par stratégie
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
            Activité réelle (nombre d'ordres, pas un P&L attribué — Alpaca n'expose aucune attribution de P&L par
            stratégie).
          </Typography>
          <StrategyActivityChart strategies={strategyActivity?.strategies ?? []} themeMode={themeMode} />
        </Paper>
      </Grid>
    </Grid>
  );
}

function sliceLastDays(points: { x: string; y: number }[], days: number): { x: string; y: number }[] {
  if (points.length === 0) return [];
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  const sliced = points.filter((p) => new Date(p.x).getTime() >= cutoff);
  // Une sparkline a besoin d'au moins 2 points pour tracer un segment —
  // avec des snapshots espacés de plusieurs heures (voir
  // `PORTFOLIO_SNAPSHOT_INTERVAL_SECONDS`), la fenêtre "1D" peut ne
  // contenir qu'un seul point réel ; repli sur les 2 derniers points CONNUS
  // plutôt que d'afficher une sparkline vide dans ce cas.
  return sliced.length >= 2 ? sliced : points.slice(-2);
}
