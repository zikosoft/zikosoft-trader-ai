// Paper-only demo checklist. It intentionally contains no strategy start or
// order action: operators first confirm the prerequisites, then use the
// existing Strategies/Agent Room screens for the demonstrated flow.

import { useState } from "react";
import { Alert, Box, Button, Chip, Paper, Stack, Typography } from "@mui/material";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import { describeError } from "../../api/client";
import {
  fetchPaperDemoReadiness,
  runPaperPreflight,
} from "../../api/demoReadiness";
import { useLivePolling } from "../../hooks/useLivePolling";
import { useI18n } from "../../i18n/I18nContext";
import { formatDateTime } from "../../i18n/formatters";

const POLL_INTERVAL_MS = 10_000;

function ReadinessLine({ label, value, color = "default" }: { label: string; value: string; color?: "default" | "success" | "warning" | "error" }) {
  return (
    <Box sx={{ display: "flex", justifyContent: "space-between", gap: 2, alignItems: "center" }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Chip size="small" label={value} color={color} variant="outlined" sx={{ flexShrink: 0 }} />
    </Box>
  );
}

function statusColor(status: string, positiveStatuses: string[]): "success" | "warning" | "error" {
  if (positiveStatuses.includes(status)) return "success";
  return status.includes("FAILED") || status === "ENGAGED" || status === "UNKNOWN" ? "error" : "warning";
}

export default function PaperDemoReadinessCard() {
  const { t, locale } = useI18n();
  const { data: readiness, error: loadError, refresh } = useLivePolling(fetchPaperDemoReadiness, POLL_INTERVAL_MS);
  const [testing, setTesting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function handlePreflight() {
    setTesting(true);
    setActionError(null);
    try {
      await runPaperPreflight();
      refresh();
    } catch (err) {
      setActionError(describeError(err));
    } finally {
      setTesting(false);
    }
  }

  const accountStatus = readiness?.account_connected ? "CONNECTED" : readiness?.account_configured ? "CONFIGURED" : "NOT_CONFIGURED";
  const accountColor = readiness?.account_connected ? "success" : "warning";

  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" component="h2" sx={{ mb: 1, display: "flex", alignItems: "center", gap: 1 }}>
        <FactCheckOutlinedIcon color={readiness?.ready_for_paper_demo ? "success" : "primary"} />
        {t("paperReadiness.title")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>{t("paperReadiness.body")}</Typography>

      {readiness && (
        <Stack spacing={1.25} sx={{ mb: 2 }}>
          <ReadinessLine
            label={t("paperReadiness.paperAccount")}
            value={t(`paperReadiness.account.${accountStatus}`)}
            color={accountColor}
          />
          <ReadinessLine
            label={t("paperReadiness.paperLock")}
            value={t(readiness.paper_url_locked ? "paperReadiness.paperLockEnabled" : "paperReadiness.paperLockInvalid")}
            color={readiness.paper_url_locked ? "success" : "error"}
          />
          <ReadinessLine
            label={t("paperReadiness.connection")}
            value={t(`paperReadiness.connectionStatus.${readiness.paper_connection_status}`)}
            color={statusColor(readiness.paper_connection_status, ["VERIFIED"])}
          />
          <ReadinessLine
            label={t("paperReadiness.mcp")}
            value={t(`paperReadiness.mcpStatus.${readiness.mcp_session_status}`)}
            color={statusColor(readiness.mcp_session_status, ["HEALTHY"])}
          />
          <ReadinessLine
            label={t("paperReadiness.options")}
            value={t("paperReadiness.optionContracts", { count: readiness.active_option_contract_count })}
            color={readiness.active_option_contract_count > 0 ? "success" : "warning"}
          />
          <ReadinessLine
            label={t("paperReadiness.killSwitch")}
            value={t(`paperReadiness.killSwitchStatus.${readiness.trading_kill_switch_status}`)}
            color={statusColor(readiness.trading_kill_switch_status, ["DISENGAGED"])}
          />
        </Stack>
      )}

      {readiness?.paper_connection_checked_at && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 2 }}>
          {t("paperReadiness.checkedAt", {
            value: formatDateTime(locale, readiness.paper_connection_checked_at, { dateStyle: "medium", timeStyle: "medium" }),
          })}
        </Typography>
      )}

      <Button
        variant="outlined"
        onClick={handlePreflight}
        disabled={testing || readiness?.account_configured === false}
      >
        {testing ? t("paperReadiness.testing") : t("paperReadiness.testConnection")}
      </Button>

      {readiness?.account_configured === false && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          {t("paperReadiness.configureFirst")}
        </Typography>
      )}
      {readiness && !readiness.ready_for_paper_demo && (
        <Alert severity="info" sx={{ mt: 2 }}>{t("paperReadiness.notReady")}</Alert>
      )}
      {readiness?.ready_for_paper_demo && (
        <Alert severity="success" sx={{ mt: 2 }}>{t("paperReadiness.ready")}</Alert>
      )}
      {loadError && <Alert severity="error" sx={{ mt: 2 }}>{describeError(loadError)}</Alert>}
      {actionError && <Alert severity="error" sx={{ mt: 2 }}>{actionError}</Alert>}
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 2 }}>
        {t("paperReadiness.nonTransactional")}
      </Typography>
    </Paper>
  );
}
