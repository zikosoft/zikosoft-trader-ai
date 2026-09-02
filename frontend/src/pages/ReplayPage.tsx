import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  LinearProgress,
  Paper,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { ApiError, describeError } from "../api/client";
import {
  advanceReplaySession,
  fetchReplayDataset,
  fetchReplaySession,
  resetReplaySession,
  type ReplayDataset,
  type ReplaySession,
} from "../api/replay";
import { formatDateTime, formatNumber } from "../i18n/formatters";
import { useI18n } from "../i18n/I18nContext";

// §écran dédié Replay (28/08 — fermeture du dernier gap réel signalé par
// Zac : `ReplayPage` était encore un `PlaceholderPage` alors que toutes les
// autres pages Overview/Strategies/Orders/Portfolio/Alerts/Settings sont
// déjà context-agnostic et fonctionnent identiquement en Paper et en
// Replay — voir AVANCEMENT.md, investigation Playwright du 28/08). Reste
// délibérément minimal par instruction explicite de Zac ("je veux juste
// que ça soit fonctionnelle, pas de travail exceptionnel") : lecture
// manuelle bougie-par-bougie uniquement, consommant le squelette Étape A de
// B19 (`GET/POST /api/replay/*`) tel quel. Pas de lecture automatique, pas
// de vitesses x1/x2/x5/x10, pas de pipeline stratégie/ordres branché — ça,
// c'est l'Étape B du Replay Engine (voir docstring backend
// `routers/replay.py`), hors scope ici.
export default function ReplayPage() {
  const { locale, t } = useI18n();
  const [dataset, setDataset] = useState<ReplayDataset | null>(null);
  const [datasetError, setDatasetError] = useState<unknown>(null);
  const [datasetLoading, setDatasetLoading] = useState(true);

  const [session, setSession] = useState<ReplaySession | null>(null);
  const [sessionError, setSessionError] = useState<unknown>(null);

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function loadDataset() {
    setDatasetLoading(true);
    setDatasetError(null);
    try {
      const d = await fetchReplayDataset();
      setDataset(d);
      await loadSession();
    } catch (err) {
      setDataset(null);
      setDatasetError(err);
    } finally {
      setDatasetLoading(false);
    }
  }

  async function loadSession() {
    setSessionError(null);
    try {
      const s = await fetchReplaySession();
      setSession(s);
    } catch (err) {
      // §pas de session démarrée pour ce contexte (404) — c'est un état
      // normal (aucun `reset`/`advance` encore appelé), pas une erreur à
      // afficher en rouge ; même discipline que le 404
      // `GET /api/portfolio/summary` ailleurs dans l'app.
      setSession(null);
      setSessionError(err);
    }
  }

  useEffect(() => {
    loadDataset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleReset() {
    setBusy(true);
    setActionError(null);
    try {
      const s = await resetReplaySession();
      setSession(s);
      setSessionError(null);
    } catch (err) {
      setActionError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleAdvance() {
    setBusy(true);
    setActionError(null);
    try {
      const s = await advanceReplaySession();
      setSession(s);
      setSessionError(null);
    } catch (err) {
      setActionError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  if (datasetLoading && !dataset && !datasetError) {
    return (
      <Box>
        <Skeleton variant="text" width={220} height={48} sx={{ mb: 2 }} />
        <Skeleton variant="rectangular" height={200} sx={{ borderRadius: 1 }} />
      </Box>
    );
  }

  // §aucun dataset produit dans cet environnement — état honnête,
  // strictement identique au message backend (D021/D047 : rien n'est
  // simulé). Générer un dataset réel exige de vraies clés Alpaca
  // (`scripts/fetch_replay_dataset.py`), indisponibles avant le hackathon
  // (cf. échange avec Zac du 28/08).
  if (!dataset && datasetError instanceof ApiError && datasetError.code === "NOT_FOUND") {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.replay")}
        </Typography>
        <Alert severity="info">
          {t("replay.noDataset", { error: datasetError.message })}
        </Alert>
      </Box>
    );
  }

  if (!dataset && datasetError) {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.replay")}
        </Typography>
        <Alert severity="error">{describeError(datasetError)}</Alert>
      </Box>
    );
  }

  if (!dataset) return null;

  // §contexte actif ≠ REPLAY (ex. Paper) — le backend le signale par un 400
  // VALIDATION_ERROR explicite ("aucun contexte REPLAY actif") sur les
  // routes de session ; `GET /dataset` reste lui accessible quel que soit
  // le contexte (métadonnées, pas d'état par contexte). On relaie le
  // message backend tel quel plutôt que d'en fabriquer un nouveau.
  const wrongContext =
    sessionError instanceof ApiError && sessionError.code === "VALIDATION_ERROR";
  const noSessionYet = sessionError instanceof ApiError && sessionError.code === "NOT_FOUND";

  return (
    <Box>
      <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
        {t("navigation.replay")}
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
          {t("replay.dataset")}
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 1 }}>
          {t("replay.datasetSummary", {
            day: dataset.trading_day,
            timezone: dataset.timezone,
            symbols: dataset.symbols.join(", "),
            bars: dataset.total_bars,
          })}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {t("replay.datasetMeta", { id: dataset.dataset_id, checksum: dataset.checksum })}
        </Typography>
      </Paper>

      {wrongContext && (
        <Alert severity="info" sx={{ mb: 2 }}>
          {t("replay.wrongContext", {
            error: (sessionError as ApiError).message,
            context: t("context.REPLAY"),
          })}
        </Alert>
      )}

      {!wrongContext && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Box
            sx={{
              display: "flex",
              flexDirection: { xs: "column", sm: "row" },
              alignItems: { xs: "stretch", sm: "center" },
              justifyContent: "space-between",
              gap: 2,
              mb: 2,
            }}
          >
            <Typography variant="h6" component="h2">
              {t("replay.session")}
            </Typography>
            <Box sx={{ display: "flex", gap: 1 }}>
              <Button variant="outlined" onClick={handleReset} disabled={busy}>
                {t("replay.reset")}
              </Button>
              <Button
                variant="contained"
                onClick={handleAdvance}
                disabled={busy || (session?.is_finished ?? false)}
              >
                {t("replay.advance")}
              </Button>
            </Box>
          </Box>

          {actionError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {actionError}
            </Alert>
          )}

          {noSessionYet && !session && (
            <Alert severity="info" sx={{ mb: 2 }}>
              {t("replay.noSession", { reset: t("replay.reset") })}
            </Alert>
          )}

          {session && (
            <>
              <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 2, flexWrap: "wrap" }}>
                <Chip
                  label={session.is_finished ? t("status.COMPLETED") : t("status.RUNNING")}
                  color={session.is_finished ? "default" : "success"}
                  variant={session.is_finished ? "outlined" : "filled"}
                />
                <Typography variant="body2" color="text.secondary">
                  {t("replay.candleProgress", {
                    current: session.current_index + 1,
                    total: session.total_bars,
                    time: formatDateTime(locale, session.current_timestamp),
                  })}
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={
                  dataset.total_bars > 0
                    ? Math.min(100, Math.max(0, (session.current_index / Math.max(dataset.total_bars - 1, 1)) * 100))
                    : 0
                }
                sx={{ mb: 2, borderRadius: 1, height: 8 }}
              />

              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t("common.symbol")}</TableCell>
                      <TableCell align="right">{t("replay.open")}</TableCell>
                      <TableCell align="right">{t("replay.high")}</TableCell>
                      <TableCell align="right">{t("replay.low")}</TableCell>
                      <TableCell align="right">{t("replay.close")}</TableCell>
                      <TableCell align="right">{t("replay.volume")}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {Object.entries(session.current_bars).map(([symbol, bar]) => (
                      <TableRow key={symbol}>
                        <TableCell>{symbol}</TableCell>
                        <TableCell align="right">{formatNumber(locale, bar.open, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</TableCell>
                        <TableCell align="right">{formatNumber(locale, bar.high, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</TableCell>
                        <TableCell align="right">{formatNumber(locale, bar.low, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</TableCell>
                        <TableCell align="right">{formatNumber(locale, bar.close, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</TableCell>
                        <TableCell align="right">{formatNumber(locale, bar.volume, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </>
          )}
        </Paper>
      )}

      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 2 }}>
        {t("replay.manualNote")}
      </Typography>
    </Box>
  );
}
