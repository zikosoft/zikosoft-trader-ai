import { Box, Chip, Typography } from "@mui/material";

// §B25 — squelette de navigation honnête pour les écrans dont le CONTENU
// réel appartient à une brique future non encore construite (même
// discipline que les placeholders déjà livrés en B01-B23 : App.tsx/
// LoginForm.tsx/ContextChooser.tsx annonçaient déjà explicitement "arrive en
// B25" plutôt que de fabriquer un faux aperçu). B25 construit la NAVIGATION
// (routes, menu, en-tête) vers ces 10 destinations — pas leur contenu, qui
// appartient chacun à sa propre brique (voir `future` ci-dessous).

type Props = {
  title: string;
  future: string;
  description: string;
};

export default function PlaceholderPage({ title, future, description }: Props) {
  return (
    <Box sx={{ maxWidth: 720 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 2 }}>
        <Typography variant="h4" component="h1">
          {title}
        </Typography>
        <Chip label={future} size="small" color="default" variant="outlined" />
      </Box>
      <Typography color="text.secondary">{description}</Typography>
    </Box>
  );
}
