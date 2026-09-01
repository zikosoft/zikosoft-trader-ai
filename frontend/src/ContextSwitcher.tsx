import { useState } from "react";
import { Box, Button, Chip, Typography } from "@mui/material";
import { describeError } from "./api/client";
import { selectContext, type ContextKind, type ContextListResponse } from "./api/context";
import { CONTEXT_COLORS } from "./theme";

// Sélecteur global de contexte, désormais dans le header (§B25 "Sélecteur
// Replay/Paper" ; auparavant une bande dédiée sous le header, §B06
// "Sélecteur global permanent dans le header", "Confirmation avant
// changement de contexte", "Badges visuels impossibles à confondre").
// Comportement STRICTEMENT inchangé depuis B06 (confirmation en deux temps
// : bouton -> état "Confirmer ?" -> clic) — seul l'habillage visuel passe
// de styles inline à Material UI (D061, voir AVANCEMENT.md).

type Props = {
  state: ContextListResponse;
  onChanged: (state: ContextListResponse) => void;
};

const LABELS: Record<ContextKind, string> = { PAPER: "Alpaca Paper", REPLAY: "Historical Replay" };

export default function ContextSwitcher({ state, onChanged }: Props) {
  const [pendingTarget, setPendingTarget] = useState<ContextKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);

  const active = state.active_kind;

  async function requestSwitch(kind: ContextKind) {
    if (kind === active) return;
    setError(null);
    setPendingTarget(kind); // 1er clic : passe en état "Confirmer ?"
  }

  async function confirmSwitch(kind: ContextKind) {
    setSwitching(true);
    setError(null);
    try {
      const result = await selectContext(kind, true);
      if ("confirmationRequired" in result) {
        setError("Le contexte actif a changé entre-temps — réessaie.");
        return;
      }
      onChanged(result);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSwitching(false);
      setPendingTarget(null);
    }
  }

  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
      {active && (
        <Chip
          label={`${active} — ${LABELS[active]}`}
          size="small"
          sx={{
            bgcolor: CONTEXT_COLORS[active],
            color: "#fff",
            fontWeight: 700,
          }}
        />
      )}
      {state.contexts
        .filter((c) => c.kind !== active)
        .map((c) =>
          pendingTarget === c.kind ? (
            <Button
              key={c.kind}
              size="small"
              variant="contained"
              color="warning"
              disabled={switching}
              onClick={() => confirmSwitch(c.kind)}
            >
              {switching ? "Changement…" : `Confirmer → ${LABELS[c.kind]}`}
            </Button>
          ) : (
            <Button
              key={c.kind}
              size="small"
              variant="outlined"
              color="inherit"
              disabled={switching || pendingTarget !== null}
              onClick={() => requestSwitch(c.kind)}
            >
              Passer en {LABELS[c.kind]}
            </Button>
          ),
        )}
      {pendingTarget && (
        <Button size="small" color="inherit" onClick={() => setPendingTarget(null)}>
          Annuler
        </Button>
      )}
      {error && (
        <Typography variant="caption" color="error">
          {error}
        </Typography>
      )}
    </Box>
  );
}
