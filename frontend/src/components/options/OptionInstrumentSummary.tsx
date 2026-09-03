import { Box, Chip, Stack, Typography } from "@mui/material";
import type { OptionInstrument } from "../../api/options";
import { formatCurrency, formatDate } from "../../i18n/formatters";
import { useI18n } from "../../i18n/I18nContext";

type Props = {
  instrument: OptionInstrument;
  dense?: boolean;
};

/**
 * Small, read-only proof of the exact contract selected before an order.
 * It is shared by Orders and Agent Room so an OCC symbol never appears
 * without its underlying, call/put direction, expiry and capped maximum loss.
 */
export default function OptionInstrumentSummary({ instrument, dense = false }: Props) {
  const { locale, t } = useI18n();
  const optionType = instrument.option_type === "call" ? t("options.call") : t("options.put");
  const expiration = formatDate(locale, `${instrument.expiration_date}T12:00:00Z`);

  return (
    <Box sx={{ minWidth: dense ? 180 : undefined }}>
      <Stack direction="row" spacing={0.75} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap" }}>
        <Chip label={optionType} size="small" color={instrument.option_type === "call" ? "success" : "warning"} variant="outlined" />
        <Typography variant={dense ? "caption" : "body2"} sx={{ fontFamily: "monospace", fontWeight: 700 }}>
          {instrument.symbol}
        </Typography>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
        {t("options.underlying")}: {instrument.underlying_symbol} · {t("options.expiry")}: {expiration}
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
        {t("options.strike")}: {formatCurrency(locale, instrument.strike_price)} · {t("options.limit")}: {formatCurrency(locale, instrument.limit_price)}
      </Typography>
      {!dense && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
          {t("options.estimatedPremium")}: {formatCurrency(locale, instrument.estimated_premium)} · {t("options.maxLoss")}: {formatCurrency(locale, instrument.max_loss)} · {t("options.spread")}: {(instrument.spread_pct * 100).toFixed(1)}%
        </Typography>
      )}
    </Box>
  );
}
