import { Chip, Dialog, DialogContent, DialogTitle, IconButton, List, ListItem, ListItemText } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { MarkerClickPayload } from "./CandlestickChart";
import { formatCurrency, formatDateTime } from "../../i18n/formatters";
import { useI18n } from "../../i18n/I18nContext";
import { localizeValue } from "../../i18n/domain";

// §B27 "Clic vers Decision Details" — Decision Details en tant qu'écran
// dédié dans l'Agent Room reste le périmètre de B28 (voir AVANCEMENT.md,
// checklist B28 "Onglets : ... Decision Details", pas encore construit).
// En attendant, ce clic ouvre les VRAIES données déjà chargées pour ce
// marqueur (ordre exécuté, proposition IA, ou rejet Risk Engine) dans une
// fenêtre inline — honnête (rien n'est fabriqué, chaque champ vient de
// `agent_decisions`/`risk_decisions`/`orders`) plutôt que de pointer vers
// une page qui n'existe pas encore.
export default function DecisionDetailsDialog({
  payload,
  onClose,
}: {
  payload: MarkerClickPayload | null;
  onClose: () => void;
}) {
  const { locale, t } = useI18n();
  return (
    <Dialog open={payload !== null} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        {payload?.kind === "order" && t("decision.orderTitle")}
        {payload?.kind === "proposal" && t("decision.proposalTitle")}
        {payload?.kind === "risk_event" && t("decision.riskTitle")}
        <IconButton onClick={onClose} size="small" aria-label={t("common.close")}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {payload?.kind === "order" && (
          <List dense disablePadding>
            <ListItem disableGutters>
              <ListItemText primary={t("orders.side")} secondary={payload.order.side === "buy" ? t("orderSide.buy") : t("orderSide.sell")} />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary={t("common.status")} secondary={localizeValue(t, `status.${payload.order.status.toUpperCase()}`, payload.order.status)} />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary={t("common.quantity")} secondary={payload.order.quantity ?? "—"} />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText
                primary={t("decision.executionPrice")}
                secondary={payload.order.filled_price !== null ? formatCurrency(locale, payload.order.filled_price) : t("common.notAvailable")}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary={t("decision.filledAt")} secondary={payload.order.filled_at ? formatDateTime(locale, payload.order.filled_at) : "—"} />
            </ListItem>
          </List>
        )}
        {payload?.kind === "proposal" && (
          <List dense disablePadding>
            <ListItem disableGutters>
              <ListItemText
                primary={t("decision.signal")}
                secondary={<Chip label={localizeValue(t, `signal.${payload.proposal.outcome}`, payload.proposal.outcome)} size="small" />}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText
                primary={t("decision.confidence")}
                secondary={payload.proposal.confidence !== null ? t("common.confidence", { value: (payload.proposal.confidence / 100).toFixed(0) }) : "—"}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary={t("decision.reasoning")} secondary={payload.proposal.reasoning_text ?? "—"} />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary={t("decision.dataTimestamp")} secondary={payload.proposal.market_data_timestamp ? formatDateTime(locale, payload.proposal.market_data_timestamp) : "—"} />
            </ListItem>
          </List>
        )}
        {payload?.kind === "risk_event" && (
          <List dense disablePadding>
            <ListItem disableGutters>
              <ListItemText
                primary={t("decision.outcome")}
                secondary={<Chip label={localizeValue(t, `riskOutcome.${payload.riskEvent.outcome}`, payload.riskEvent.outcome)} size="small" color="error" />}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText
                primary={t("decision.reasons")}
                secondary={payload.riskEvent.reasons.length > 0 ? payload.riskEvent.reasons.join(", ") : "—"}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary={t("decision.dataTimestamp")} secondary={payload.riskEvent.market_data_timestamp ? formatDateTime(locale, payload.riskEvent.market_data_timestamp) : "—"} />
            </ListItem>
          </List>
        )}
      </DialogContent>
    </Dialog>
  );
}
