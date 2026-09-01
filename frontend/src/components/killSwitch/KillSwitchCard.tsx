// §B31 — carte "Kill switch trading" de l'écran Settings : bouton global
// très visible (D... voir AVANCEMENT.md checklist B31) + confirmation
// renforcée (phrase à taper, pas un simple `window.confirm`) pour engager
// OU désengager. La bannière globale (`components/KillSwitchBanner.tsx`)
// reste la source de vérité "très visible" partout ailleurs dans l'app —
// cette carte est le point d'ACTION.

import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  List,
  ListItem,
  ListItemText,
  Paper,
  TextField,
  Typography,
} from "@mui/material";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { useLivePolling } from "../../hooks/useLivePolling";
import {
  disengageKillSwitch,
  engageKillSwitch,
  fetchKillSwitchHistory,
  fetchKillSwitchStatus,
  type KillSwitchEvent,
} from "../../api/killSwitch";
import { describeError } from "../../api/client";

const POLL_INTERVAL_MS = 5000;
const ENGAGE_PHRASE = "ARRÊTER LE TRADING";
const DISENGAGE_PHRASE = "REPRENDRE LE TRADING";

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("fr-FR");
  } catch {
    return iso;
  }
}

function ConfirmDialog({
  open,
  title,
  phrase,
  confirmLabel,
  confirmColor,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  phrase: string;
  confirmLabel: string;
  confirmColor: "error" | "success";
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [typedPhrase, setTypedPhrase] = useState("");

  const canConfirm = reason.trim().length >= 3 && typedPhrase === phrase && !busy;

  const handleClose = () => {
    setReason("");
    setTypedPhrase("");
    onCancel();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ mb: 2 }}>
          Cette action est immédiate et laisse une trace d'audit permanente. Indiquez une raison, puis tapez exactement
          « {phrase} » pour confirmer.
        </DialogContentText>
        <TextField
          label="Raison"
          fullWidth
          multiline
          minRows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          sx={{ mb: 2 }}
        />
        <TextField
          label={`Tapez « ${phrase} » pour confirmer`}
          fullWidth
          value={typedPhrase}
          onChange={(e) => setTypedPhrase(e.target.value)}
          error={typedPhrase.length > 0 && typedPhrase !== phrase}
        />
        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={busy}>
          Annuler
        </Button>
        <Button
          variant="contained"
          color={confirmColor}
          disabled={!canConfirm}
          onClick={() => onConfirm(reason.trim())}
        >
          {busy ? "En cours…" : confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function EventLine({ event }: { event: KillSwitchEvent }) {
  const engaged = event.action === "KILL_SWITCH_ENGAGED";
  return (
    <ListItem disableGutters>
      <ListItemText
        primary={
          <>
            <Chip
              label={engaged ? "Engagé" : "Désengagé"}
              size="small"
              color={engaged ? "error" : "success"}
              variant="outlined"
              sx={{ mr: 1 }}
            />
            {event.reason ?? "—"}
          </>
        }
        secondary={formatDate(event.occurred_at)}
      />
    </ListItem>
  );
}

export default function KillSwitchCard() {
  const { data: status, refresh: refreshStatus } = useLivePolling(fetchKillSwitchStatus, POLL_INTERVAL_MS);
  const { data: history, refresh: refreshHistory } = useLivePolling(() => fetchKillSwitchHistory(10), POLL_INTERVAL_MS);
  const [dialog, setDialog] = useState<"engage" | "disengage" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const engaged = status?.engaged ?? false;

  async function handleEngage(reason: string) {
    setBusy(true);
    setError(null);
    try {
      await engageKillSwitch(reason);
      setDialog(null);
      refreshStatus();
      refreshHistory();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDisengage(reason: string) {
    setBusy(true);
    setError(null);
    try {
      await disengageKillSwitch(reason);
      setDialog(null);
      refreshStatus();
      refreshHistory();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" component="h2" sx={{ mb: 1, display: "flex", alignItems: "center", gap: 1 }}>
        <WarningAmberIcon color={engaged ? "error" : "action"} />
        Kill switch trading
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Interrompt immédiatement le trading : suspend toutes les stratégies actives, bloque toute nouvelle proposition
        et l'Order Worker, annule les ordres ouverts éligibles. La reprise n'est jamais automatique.
      </Typography>

      {/* §B31 bug trouvé pendant la vérification interactive (mobile,
          390px) : `justifyContent: space-between` en row fixe compressait
          le bouton ("ARRÊTER LE TRADING") jusqu'à le faire passer sur 3
          lignes, en partie recouvert par le widget de chat flottant —
          même pattern de correctif que `ContextChooser.tsx`
          (`direction={{ xs: "column", sm: "row" }}`) : la ligne
          statut+bouton s'empile verticalement sous le seuil `sm`, le
          bouton passe en pleine largeur pour rester actionnable au pouce. */}
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
        <Box>
          <Chip
            label={engaged ? "Trading suspendu" : "Trading actif"}
            color={engaged ? "error" : "success"}
            variant={engaged ? "filled" : "outlined"}
          />
          {status?.last_event && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Dernier événement : « {status.last_event.reason ?? "—"} » — {formatDate(status.last_event.occurred_at)}
            </Typography>
          )}
        </Box>
        {engaged ? (
          <Button
            variant="contained"
            color="success"
            onClick={() => setDialog("disengage")}
            sx={{ flexShrink: 0 }}
          >
            Reprendre le trading
          </Button>
        ) : (
          <Button variant="contained" color="error" onClick={() => setDialog("engage")} sx={{ flexShrink: 0 }}>
            Arrêter le trading
          </Button>
        )}
      </Box>

      {history && history.length > 0 && (
        <>
          <Divider sx={{ mb: 1 }} />
          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
            Historique récent
          </Typography>
          <List dense disablePadding>
            {history.map((event, i) => (
              // §pas d'id serveur exposé par ce schéma de sortie — index +
              // horodatage suffisent, liste en lecture seule non réordonnée.
              <EventLine key={`${event.occurred_at}-${i}`} event={event} />
            ))}
          </List>
        </>
      )}

      <ConfirmDialog
        open={dialog === "engage"}
        title="Arrêter le trading"
        phrase={ENGAGE_PHRASE}
        confirmLabel="Arrêter le trading"
        confirmColor="error"
        busy={busy}
        error={error}
        onCancel={() => {
          setDialog(null);
          setError(null);
        }}
        onConfirm={handleEngage}
      />
      <ConfirmDialog
        open={dialog === "disengage"}
        title="Reprendre le trading"
        phrase={DISENGAGE_PHRASE}
        confirmLabel="Reprendre le trading"
        confirmColor="success"
        busy={busy}
        error={error}
        onCancel={() => {
          setDialog(null);
          setError(null);
        }}
        onConfirm={handleDisengage}
      />
    </Paper>
  );
}
