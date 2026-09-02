import { Box, Chip, Typography } from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";

// §B28 checklist "Onglet Ask Ziko AI (placeholder)" — même discipline
// honnête que `PlaceholderPage.tsx` (B25) : annonce clairement la brique
// propriétaire (B29) plutôt que de fabriquer un faux aperçu de chat. Un
// composant dédié (pas une réutilisation de `PlaceholderPage`) car ce
// placeholder doit tenir dans un panneau étroit (mode compact, ~340px) —
// `PlaceholderPage` suppose la pleine largeur d'une page routée.

export default function AskZikoTab({ dense = false }: { dense?: boolean }) {
  const { t } = useI18n();
  return (
    <Box sx={{ p: dense ? 1.5 : 2 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1, flexWrap: "wrap" }}>
        <Typography variant={dense ? "body2" : "subtitle1"} sx={{ fontWeight: 600 }}>
          {t("agentRoom.askZiko")}
        </Typography>
        <Chip label={t("agentRoom.comingInB29")} size="small" variant="outlined" />
      </Box>
      <Typography variant="body2" color="text.secondary">
        {t("agentRoom.askPlaceholder")}
      </Typography>
    </Box>
  );
}
