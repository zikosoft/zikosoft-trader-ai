import { Chip, Dialog, DialogContent, DialogTitle, IconButton, List, ListItem, ListItemText } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { MarkerClickPayload } from "./CandlestickChart";

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
  return (
    <Dialog open={payload !== null} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        {payload?.kind === "order" && "Ordre exécuté"}
        {payload?.kind === "proposal" && "Proposition IA"}
        {payload?.kind === "risk_event" && "Décision Risk Engine"}
        <IconButton onClick={onClose} size="small">
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {payload?.kind === "order" && (
          <List dense disablePadding>
            <ListItem disableGutters>
              <ListItemText primary="Sens" secondary={payload.order.side === "buy" ? "Achat" : "Vente"} />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary="Statut" secondary={payload.order.status} />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary="Quantité" secondary={payload.order.quantity ?? "—"} />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText
                primary="Prix d'exécution"
                secondary={payload.order.filled_price !== null ? `${payload.order.filled_price} $` : "non disponible"}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary="Exécuté le" secondary={payload.order.filled_at ?? "—"} />
            </ListItem>
          </List>
        )}
        {payload?.kind === "proposal" && (
          <List dense disablePadding>
            <ListItem disableGutters>
              <ListItemText
                primary="Signal"
                secondary={<Chip label={payload.proposal.outcome} size="small" />}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText
                primary="Confiance"
                secondary={payload.proposal.confidence !== null ? `${(payload.proposal.confidence / 100).toFixed(0)}%` : "—"}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary="Raisonnement" secondary={payload.proposal.reasoning_text ?? "—"} />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary="Horodatage des données" secondary={payload.proposal.market_data_timestamp ?? "—"} />
            </ListItem>
          </List>
        )}
        {payload?.kind === "risk_event" && (
          <List dense disablePadding>
            <ListItem disableGutters>
              <ListItemText
                primary="Issue"
                secondary={<Chip label={payload.riskEvent.outcome} size="small" color="error" />}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText
                primary="Raisons"
                secondary={payload.riskEvent.reasons.length > 0 ? payload.riskEvent.reasons.join(", ") : "—"}
              />
            </ListItem>
            <ListItem disableGutters>
              <ListItemText primary="Horodatage des données" secondary={payload.riskEvent.market_data_timestamp ?? "—"} />
            </ListItem>
          </List>
        )}
      </DialogContent>
    </Dialog>
  );
}
