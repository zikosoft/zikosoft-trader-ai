import { useState } from "react";
import { Alert, Box, Button, Card, CardActions, CardContent, Container, Stack, Typography } from "@mui/material";
import { describeError } from "./api/client";
import { selectContext, type ContextKind, type ContextListResponse } from "./api/context";

// Écran "Choose your experience" — comportement inchangé depuis B06,
// habillage Material UI ajouté en B25 (§commentaire d'origine : "le vrai
// habillage visuel arrive en B25").

type Props = {
  onSelected: (state: ContextListResponse) => void;
};

const CARDS: { kind: ContextKind; title: string; description: string }[] = [
  {
    kind: "REPLAY",
    title: "Historical Replay",
    description:
      "Rejoue un jeu de données historique figé, à vitesse contrôlée — aucun compte Alpaca requis, aucun risque, pratique pour observer les agents sans attendre le marché réel.",
  },
  {
    kind: "PAPER",
    title: "Alpaca Paper",
    description:
      "Connecté à un compte Alpaca Paper (fonds simulés, aucun argent réel) — le marché et les données sont réels, les ordres ne le sont pas. Nécessite un compte Alpaca (voir B07).",
  },
];

export default function ContextChooser({ onSelected }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<ContextKind | null>(null);

  async function handleChoose(kind: ContextKind) {
    setPending(kind);
    setError(null);
    try {
      const result = await selectContext(kind);
      if ("confirmationRequired" in result) {
        // Ne devrait pas arriver ici (aucun contexte actif au premier
        // choix) — filet de sécurité si l'état a changé entre-temps.
        setError("Un contexte est déjà actif — rechargez la page.");
        return;
      }
      onSelected(result);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPending(null);
    }
  }

  return (
    <Container maxWidth="md" sx={{ py: 6 }}>
      <Typography variant="h4" component="h1" sx={{ mb: 1 }}>
        Choose your experience
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Comment veux-tu utiliser ZikosoftTrader AI ?
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        {CARDS.map((card) => (
          <Card key={card.kind} variant="outlined" sx={{ flex: 1 }}>
            <CardContent>
              <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
                {card.title}
              </Typography>
              <Typography color="text.secondary">{card.description}</Typography>
            </CardContent>
            <CardActions>
              <Box sx={{ p: 1 }}>
                <Button
                  variant="contained"
                  disabled={pending !== null}
                  onClick={() => handleChoose(card.kind)}
                >
                  {pending === card.kind ? "Activation…" : `Choisir ${card.title}`}
                </Button>
              </Box>
            </CardActions>
          </Card>
        ))}
      </Stack>
    </Container>
  );
}
