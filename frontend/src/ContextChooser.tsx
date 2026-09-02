import { useState } from "react";
import { Alert, Box, Button, Card, CardActions, CardContent, Container, Stack, Typography } from "@mui/material";
import { describeError } from "./api/client";
import { selectContext, type ContextKind, type ContextListResponse } from "./api/context";
import { contextLabel } from "./i18n/domain";
import { useI18n } from "./i18n/I18nContext";

// Écran "Choose your experience" — comportement inchangé depuis B06,
// habillage Material UI ajouté en B25 (§commentaire d'origine : "le vrai
// habillage visuel arrive en B25").

type Props = {
  onSelected: (state: ContextListResponse) => void;
};

const CARDS: { kind: ContextKind; descriptionKey: string }[] = [
  {
    kind: "REPLAY",
    descriptionKey: "context.replayDescription",
  },
  {
    kind: "PAPER",
    descriptionKey: "context.paperDescription",
  },
];

export default function ContextChooser({ onSelected }: Props) {
  const { t } = useI18n();
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
        setError(t("context.alreadyActive"));
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
        {t("context.chooserTitle")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        {t("context.chooserBody")}
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
                {contextLabel(t, card.kind)}
              </Typography>
              <Typography color="text.secondary">{t(card.descriptionKey)}</Typography>
            </CardContent>
            <CardActions>
              <Box sx={{ p: 1 }}>
                <Button
                  variant="contained"
                  disabled={pending !== null}
                  onClick={() => handleChoose(card.kind)}
                >
                  {pending === card.kind
                    ? t("context.activating")
                    : t("context.choose", { context: contextLabel(t, card.kind) })}
                </Button>
              </Box>
            </CardActions>
          </Card>
        ))}
      </Stack>
    </Container>
  );
}
