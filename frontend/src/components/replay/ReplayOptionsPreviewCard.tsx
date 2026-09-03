import { Alert, Box, Chip, Paper, Stack, Typography } from "@mui/material";
import type { ReplayOptionsPreview } from "../../api/replay";
import OptionInstrumentSummary from "../options/OptionInstrumentSummary";
import { useI18n } from "../../i18n/I18nContext";
import { localizeValue } from "../../i18n/domain";

type Props = {
  preview: ReplayOptionsPreview | null;
  loading: boolean;
  error: string | null;
};

/**
 * Makes the options mapping visible without ever presenting Replay as a
 * broker simulation. Its backing endpoint is pure/read-only and has no
 * connection to agents, Claude, the Risk Engine or the Order Worker.
 */
export default function ReplayOptionsPreviewCard({ preview, loading, error }: Props) {
  const { t } = useI18n();

  return (
    <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
      <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
        {t("replay.optionsPreview")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        {t("replay.optionsPreviewBody")}
      </Typography>
      <Alert severity="warning" sx={{ mb: 2 }}>
        {t("replay.optionsPreviewSynthetic")}
      </Alert>

      {loading && <Typography color="text.secondary">{t("common.loading")}</Typography>}
      {error && <Alert severity="error">{error}</Alert>}
      {preview && !loading && !error && (
        <>
          <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", alignItems: "center", mb: 1.5 }}>
            <Chip label={localizeValue(t, `signal.${preview.signal}`, preview.signal)} size="small" />
            <Chip label={t(`replay.optionsAction.${preview.option_action}`)} size="small" variant="outlined" />
            <Chip label={t("replay.optionsPreviewExistingStrategy")} size="small" variant="outlined" />
          </Stack>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            {t(`replay.optionsReason.${preview.signal_reasoning_code}`)}
          </Typography>
          {preview.option_instrument ? (
            <Box sx={{ mb: 1.5 }}>
              <OptionInstrumentSummary instrument={preview.option_instrument} />
            </Box>
          ) : (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              {t("replay.optionsPreviewNoContract")}
            </Typography>
          )}
          <Stack spacing={0.5}>
            <Typography variant="caption" color="text.secondary">
              {t("replay.optionsPreviewRisk")}: {t("replay.optionsPreviewRiskNotEvaluated")}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t("replay.optionsPreviewExecution")}: {t("replay.optionsPreviewNotSent")}
            </Typography>
          </Stack>
        </>
      )}
    </Paper>
  );
}
