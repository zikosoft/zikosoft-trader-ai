import { FormEvent, useEffect, useState } from "react";
import { Alert, Box, Button, Chip, CircularProgress, Stack, TextField, Typography } from "@mui/material";
import SendOutlinedIcon from "@mui/icons-material/SendOutlined";
import { askZikoAboutDecision, type AskZikoResponse } from "../../api/agentRoom";
import { describeError } from "../../api/client";
import { useI18n } from "../../i18n/I18nContext";
import { useAgentRoom } from "../../useAgentRoom";

const MAX_QUESTION_CHARS = 600;

// The UI intentionally holds only the latest answer for the selected
// decision. This avoids turning the feature into an unbounded AI chat and
// makes the one-question / one-budget-reservation rule visible in practice.
export default function AskZikoTab({ dense = false }: { dense?: boolean }) {
  const { locale, t } = useI18n();
  const { selectedWindow } = useAgentRoom();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskZikoResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    setQuestion("");
    setAnswer(null);
    setError(null);
  }, [selectedWindow?.strategyId, selectedWindow?.symbol, selectedWindow?.marketDataTimestamp]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!selectedWindow || !trimmedQuestion || sending) return;

    setSending(true);
    setError(null);
    try {
      const result = await askZikoAboutDecision({
        strategyId: selectedWindow.strategyId,
        symbol: selectedWindow.symbol,
        marketDataTimestamp: selectedWindow.marketDataTimestamp,
        question: trimmedQuestion,
        locale,
      });
      setAnswer(result);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSending(false);
    }
  }

  if (!selectedWindow) {
    return (
      <Box sx={{ p: dense ? 1.5 : 2 }}>
        <Typography variant="body2" color="text.secondary">
          {t("agentRoom.askNeedDecision")}
        </Typography>
      </Box>
    );
  }

  return (
    <Box component="form" onSubmit={submit} sx={{ height: "100%", overflowY: "auto", p: dense ? 1 : 1.5 }}>
      <Stack spacing={1.25}>
        <Box>
          <Typography variant={dense ? "body2" : "subtitle1"} sx={{ fontWeight: 600 }}>
            {t("agentRoom.askZiko")}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.25 }}>
            {t("agentRoom.askIntro")}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
            {t("agentRoom.askScopedDecision", {
              symbol: selectedWindow.symbol,
              timestamp: selectedWindow.marketDataTimestamp,
            })}
          </Typography>
        </Box>

        <TextField
          label={t("agentRoom.askQuestionLabel")}
          placeholder={t("agentRoom.askQuestionPlaceholder")}
          value={question}
          onChange={(event) => setQuestion(event.target.value.slice(0, MAX_QUESTION_CHARS))}
          multiline
          minRows={dense ? 2 : 3}
          fullWidth
          inputProps={{ maxLength: MAX_QUESTION_CHARS }}
          helperText={t("agentRoom.askQuestionLimit", { count: question.length, max: MAX_QUESTION_CHARS })}
        />

        <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
          <Button
            type="submit"
            variant="contained"
            size="small"
            startIcon={sending ? <CircularProgress color="inherit" size={14} /> : <SendOutlinedIcon />}
            disabled={sending || !question.trim()}
          >
            {sending ? t("agentRoom.askSending") : t("agentRoom.askSubmit")}
          </Button>
        </Box>

        {error && <Alert severity="error">{error}</Alert>}

        {answer && (
          <Alert severity="info" icon={false} aria-live="polite">
            <Stack spacing={0.75}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, flexWrap: "wrap" }}>
                <Typography variant="subtitle2">{t("agentRoom.askAnswer")}</Typography>
                <Chip
                  size="small"
                  variant="outlined"
                  label={t(answer.source === "claude" ? "agentRoom.askClaudeSource" : "agentRoom.askFallbackSource")}
                />
              </Box>
              <Typography variant="body2">{answer.answer}</Typography>
            </Stack>
          </Alert>
        )}
      </Stack>
    </Box>
  );
}
