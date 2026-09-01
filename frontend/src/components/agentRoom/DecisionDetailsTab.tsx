import { useEffect, useState } from "react";
import { Alert, Box, Chip, CircularProgress, Divider, Paper, Stack, Typography } from "@mui/material";
import { fetchDecisionChain, type DecisionChainResponse } from "../../api/agentRoom";
import { useAgentRoom } from "../../useAgentRoom";
import { agentColor } from "./agentMeta";

// §B28 "Decision Details" (checklist "lien stratégie/risque/ordre") —
// reconstitue la chaîne PROPOSAL → CRITIQUE → décision Risk Engine →
// EXPLANATION → Ordre pour la fenêtre `(strategy_id, symbol,
// market_data_timestamp)` sélectionnée depuis le Live Debate. Chaque
// maillon absent est affiché honnêtement "en attente" (chaîne asynchrone,
// voir `backend/app/agent_room.py`) — jamais une erreur, jamais un maillon
// fabriqué.

const POLL_INTERVAL_MS = 4000;

type LoadState = {
  data: DecisionChainResponse | null;
  error: unknown;
  loading: boolean;
};

function useDecisionChain(): LoadState {
  const { selectedWindow } = useAgentRoom();
  const [state, setState] = useState<LoadState>({ data: null, error: null, loading: false });

  useEffect(() => {
    if (!selectedWindow) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    const activeWindow = selectedWindow;
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));

    async function load() {
      try {
        const result = await fetchDecisionChain(activeWindow.strategyId, activeWindow.symbol, activeWindow.marketDataTimestamp);
        if (!cancelled) setState({ data: result, error: null, loading: false });
      } catch (err) {
        if (!cancelled) setState((s) => ({ ...s, error: err, loading: false }));
      }
    }

    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWindow?.strategyId, selectedWindow?.symbol, selectedWindow?.marketDataTimestamp]);

  return state;
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function ChainSection({
  title,
  color,
  present,
  dense,
  children,
}: {
  title: string;
  color: string;
  present: boolean;
  dense: boolean;
  children?: React.ReactNode;
}) {
  return (
    <Paper variant="outlined" sx={{ p: dense ? 1 : 1.5, opacity: present ? 1 : 0.6 }}>
      <Typography variant={dense ? "caption" : "subtitle2"} sx={{ color, fontWeight: 700 }}>
        {title}
      </Typography>
      {present ? (
        <Box sx={{ mt: 0.5 }}>{children}</Box>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          En attente…
        </Typography>
      )}
    </Paper>
  );
}

export default function DecisionDetailsTab({ dense = false }: { dense?: boolean }) {
  const { selectedWindow } = useAgentRoom();
  const { data, error, loading } = useDecisionChain();

  if (!selectedWindow) {
    return (
      <Box sx={{ p: dense ? 1 : 2 }}>
        <Typography variant="body2" color="text.secondary">
          Cliquez un message dans l'onglet Live Debate pour afficher sa chaîne de décision complète (proposition,
          critique, décision du Risk Engine, explication, ordre).
        </Typography>
      </Box>
    );
  }

  if (loading && !data) {
    // §B10 checklist "indicateur de latence IA" — voir même correctif dans
    // `LiveDebateTab.tsx` (audit B10 du 28/08).
    return (
      <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, p: 3 }}>
        <CircularProgress size={24} />
        <Typography variant="body2" color="text.secondary">
          Analyse en cours, cela peut prendre quelques secondes…
        </Typography>
      </Box>
    );
  }

  if (error || !data) {
    return (
      <Alert severity="error" sx={{ m: dense ? 1 : 2 }}>
        Impossible de charger la chaîne de décision.
      </Alert>
    );
  }

  return (
    <Box sx={{ height: "100%", overflowY: "auto", p: dense ? 1 : 1.5 }}>
      <Box sx={{ mb: 1 }}>
        <Typography variant={dense ? "body2" : "subtitle1"} sx={{ fontWeight: 600 }}>
          {data.strategy_name ?? "Stratégie"} {data.strategy_type_code ? `(${data.strategy_type_code})` : ""} —{" "}
          {data.symbol}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Bougie : {data.market_data_timestamp ?? "—"}
        </Typography>
      </Box>
      <Divider sx={{ mb: 1 }} />
      <Stack spacing={1}>
        <ChainSection title="Proposition (Strategy Agent)" color={agentColor("strategy_agent")} present={!!data.proposal} dense={dense}>
          {data.proposal && (
            <>
              <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", alignItems: "center" }}>
                <Chip label={data.proposal.outcome} size="small" />
                {data.proposal.confidence !== null && (
                  <Chip label={`Confiance ${(data.proposal.confidence / 100).toFixed(0)}%`} size="small" variant="outlined" />
                )}
                <Typography variant="caption" color="text.secondary">
                  {formatTimestamp(data.proposal.created_at)}
                </Typography>
              </Stack>
              {data.proposal.reasoning_text && (
                <Typography variant="body2" sx={{ mt: 0.5 }}>
                  {data.proposal.reasoning_text}
                </Typography>
              )}
            </>
          )}
        </ChainSection>

        <ChainSection title="Critique (Risk Critic Agent)" color={agentColor("risk_critic_agent")} present={!!data.critique} dense={dense}>
          {data.critique && (
            <>
              <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", alignItems: "center" }}>
                <Chip label={data.critique.outcome} size="small" />
                {data.critique.confidence !== null && (
                  <Chip label={`Confiance ${(data.critique.confidence / 100).toFixed(0)}%`} size="small" variant="outlined" />
                )}
                <Typography variant="caption" color="text.secondary">
                  {formatTimestamp(data.critique.created_at)}
                </Typography>
              </Stack>
              {data.critique.reasoning_text && (
                <Typography variant="body2" sx={{ mt: 0.5 }}>
                  {data.critique.reasoning_text}
                </Typography>
              )}
            </>
          )}
        </ChainSection>

        <ChainSection title="Décision (Risk Engine)" color={agentColor("risk_engine")} present={!!data.risk_decision} dense={dense}>
          {data.risk_decision && (
            <>
              <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", alignItems: "center" }}>
                <Chip label={data.risk_decision.outcome} size="small" />
                <Typography variant="caption" color="text.secondary">
                  {formatTimestamp(data.risk_decision.created_at)}
                </Typography>
              </Stack>
              {data.risk_decision.reasons.length > 0 && (
                <Typography variant="body2" sx={{ mt: 0.5 }}>
                  {data.risk_decision.reasons.map(String).join(" · ")}
                </Typography>
              )}
            </>
          )}
        </ChainSection>

        <ChainSection
          title="Explication (Execution & Explanation Agent)"
          color={agentColor("execution_explanation_agent")}
          present={!!data.explanation}
          dense={dense}
        >
          {data.explanation && (
            <>
              <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", alignItems: "center" }}>
                <Chip label={data.explanation.outcome} size="small" />
                <Typography variant="caption" color="text.secondary">
                  {formatTimestamp(data.explanation.created_at)}
                </Typography>
              </Stack>
              {data.explanation.novice_summary && (
                <Typography variant="body2" sx={{ mt: 0.5 }}>
                  {data.explanation.novice_summary}
                </Typography>
              )}
              {data.explanation.expert_summary && (
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block", fontStyle: "italic" }}>
                  {data.explanation.expert_summary}
                </Typography>
              )}
            </>
          )}
        </ChainSection>

        <ChainSection title="Ordre" color="text.primary" present={!!data.order} dense={dense}>
          {data.order && (
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", alignItems: "center" }}>
              <Chip label={data.order.side} size="small" />
              <Chip label={data.order.status} size="small" variant="outlined" />
              {data.order.notional !== null && <Typography variant="body2">{data.order.notional} $</Typography>}
              {data.order.quantity !== null && <Typography variant="body2">{data.order.quantity} titres</Typography>}
            </Stack>
          )}
        </ChainSection>
      </Stack>
    </Box>
  );
}
