import { Box, Chip, Typography } from "@mui/material";

// §B28 checklist "Onglet Ask Ziko AI (placeholder)" — même discipline
// honnête que `PlaceholderPage.tsx` (B25) : annonce clairement la brique
// propriétaire (B29) plutôt que de fabriquer un faux aperçu de chat. Un
// composant dédié (pas une réutilisation de `PlaceholderPage`) car ce
// placeholder doit tenir dans un panneau étroit (mode compact, ~340px) —
// `PlaceholderPage` suppose la pleine largeur d'une page routée.

export default function AskZikoTab({ dense = false }: { dense?: boolean }) {
  return (
    <Box sx={{ p: dense ? 1.5 : 2 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1, flexWrap: "wrap" }}>
        <Typography variant={dense ? "body2" : "subtitle1"} sx={{ fontWeight: 600 }}>
          Ask Ziko AI
        </Typography>
        <Chip label="Arrive en B29" size="small" variant="outlined" />
      </Box>
      <Typography variant="body2" color="text.secondary">
        Le chat conversationnel avec Ziko (questions libres sur une décision, une stratégie ou le portefeuille)
        arrive avec la brique B29 — cet onglet reste un placeholder honnête tant que ce backend n'existe pas.
      </Typography>
    </Box>
  );
}
