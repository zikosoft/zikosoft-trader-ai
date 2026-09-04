import { useEffect, useRef } from "react";
import { Alert, Avatar, Box, Chip, CircularProgress, Paper, Stack, Typography } from "@mui/material";
import { fetchAgentMessages, type AgentMessage } from "../../api/agentRoom";
import { useLivePolling } from "../../hooks/useLivePolling";
import { useAgentRoom } from "../../useAgentRoom";
import { agentColor, agentInitials, agentLabel, stateMeta } from "./agentMeta";
import { formatDateTime } from "../../i18n/formatters";
import { useI18n } from "../../i18n/I18nContext";

// §B28 "Live Debate" (checklist : "événements réels uniquement, jamais
// fabriqués | avatar/couleur par agent | horodatage | état | confiance |
// preuves | lien stratégie/risque/ordre | temps réel via polling, D058").
// Interroge `GET /api/agents/room/messages` — chaque ligne affichée EST une
// ligne `agent_messages` réellement écrite par un agent (voir D073), jamais
// une donnée synthétisée côté frontend.

const POLL_INTERVAL_MS = 4000;

function windowKeyFromPayload(
  payload: Record<string, unknown>,
): { strategyId: string; symbol: string; marketDataTimestamp: string } | null {
  const strategyId = payload.strategy_id;
  const symbol = payload.symbol;
  const marketDataTimestamp = payload.market_data_timestamp;
  if (typeof strategyId === "string" && typeof symbol === "string" && typeof marketDataTimestamp === "string") {
    return { strategyId, symbol, marketDataTimestamp };
  }
  return null;
}

function evidenceChips(payload: Record<string, unknown>, t: (key: string) => string): { label: string; items: string[] } | null {
  const riskFlags = payload.risk_flags;
  if (Array.isArray(riskFlags) && riskFlags.length > 0) {
    return { label: t("agentRoom.riskSignals"), items: riskFlags.map(String) };
  }
  const reasons = payload.reasons;
  if (Array.isArray(reasons) && reasons.length > 0) {
    return { label: t("decision.reasons"), items: reasons.map(String) };
  }
  return null;
}

function MessageItem({ message, dense }: { message: AgentMessage; dense: boolean }) {
  const { locale, t } = useI18n();
  const { selectDecision } = useAgentRoom();
  const color = agentColor(message.agent_type);
  const state = stateMeta(message.state, t);
  const confidence = message.payload.confidence;
  const evidence = evidenceChips(message.payload, t);
  const expertSummary =
    message.agent_type === "execution_explanation_agent" && typeof message.payload.expert_summary === "string"
      ? message.payload.expert_summary
      : null;
  const windowKey = windowKeyFromPayload(message.payload);

  return (
    <Paper
      variant="outlined"
      onClick={windowKey ? () => selectDecision(windowKey) : undefined}
      sx={{
        p: dense ? 1 : 1.5,
        display: "flex",
        gap: 1,
        cursor: windowKey ? "pointer" : "default",
        "&:hover": windowKey ? { borderColor: "primary.main" } : undefined,
      }}
    >
      <Avatar sx={{ bgcolor: color, width: dense ? 28 : 36, height: dense ? 28 : 36, fontSize: dense ? "0.65rem" : "0.8rem" }}>
        {agentInitials(message.agent_type)}
      </Avatar>
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap" }}>
          <Typography variant={dense ? "caption" : "body2"} sx={{ fontWeight: 600 }}>
            {agentLabel(message.agent_type, t)}
          </Typography>
          <Chip label={state.label} color={state.color} size="small" />
          {typeof confidence === "number" && (
            <Chip label={t("common.confidence", { value: (confidence / 100).toFixed(0) })} size="small" variant="outlined" />
          )}
          <Typography variant="caption" color="text.secondary" sx={{ ml: "auto" }}>
            {formatDateTime(locale, message.occurred_at)}
          </Typography>
        </Stack>
        <Typography variant={dense ? "caption" : "body2"} sx={{ mt: 0.5, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {message.content}
        </Typography>
        {expertSummary && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block", fontStyle: "italic" }}>
            {t("agentRoom.expertSummary", { summary: expertSummary })}
          </Typography>
        )}
        {evidence && (
          <Stack direction="row" spacing={0.5} useFlexGap sx={{ mt: 0.5, flexWrap: "wrap" }}>
            <Typography variant="caption" color="text.secondary">
              {evidence.label} :
            </Typography>
            {evidence.items.map((item, idx) => (
              <Chip key={`${item}-${idx}`} label={item} size="small" variant="outlined" />
            ))}
          </Stack>
        )}
        {windowKey && (
          <Typography variant="caption" color="primary.main" sx={{ mt: 0.5, display: "block" }}>
            {t("agentRoom.viewDecisionChain")} →
          </Typography>
        )}
      </Box>
    </Paper>
  );
}

export default function LiveDebateTab({ dense = false }: { dense?: boolean }) {
  const { t } = useI18n();
  const { data, error, loading } = useLivePolling(() => fetchAgentMessages(100), POLL_INTERVAL_MS);
  const scrollRef = useRef<HTMLDivElement>(null);
  const messages = data?.messages ?? [];

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  if (loading && !data) {
    // §B10 checklist "indicateur de latence IA" — trouvé absent le 28/08
    // (audit B10) : un spinner seul, sans texte, ne dit pas à Zac/un jury
    // qu'une analyse IA peut prendre plusieurs secondes (jamais un blocage
    // silencieux inexpliqué).
    return (
      <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, p: 3 }}>
        <CircularProgress size={24} />
        <Typography variant="body2" color="text.secondary">
          {t("agentRoom.analysisInProgress")}
        </Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error" sx={{ m: dense ? 1 : 2 }}>
        {t("agentRoom.loadMessagesError")}
      </Alert>
    );
  }

  if (messages.length === 0) {
    return (
      <Box sx={{ p: dense ? 1 : 2 }}>
        <Typography variant="body2" color="text.secondary">
          {t("agentRoom.noMessages")}
        </Typography>
      </Box>
    );
  }

  return (
    <Box ref={scrollRef} sx={{ height: "100%", overflowY: "auto", p: dense ? 1 : 1.5 }}>
      <Stack spacing={1}>
        {messages.map((message) => (
          <MessageItem key={message.id} message={message} dense={dense} />
        ))}
      </Stack>
    </Box>
  );
}
