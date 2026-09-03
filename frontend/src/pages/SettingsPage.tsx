import { Box, Button, Divider, List, ListItem, ListItemText, Paper, Typography } from "@mui/material";
import { useOutletContext } from "react-router-dom";
import type { AppShellOutletContext } from "../AppShell";
import KillSwitchCard from "../components/killSwitch/KillSwitchCard";
import AiGovernanceCard from "../components/aiGovernance/AiGovernanceCard";
import AssetCatalogCard from "../components/assets/AssetCatalogCard";
import ProfileCard from "../components/profile/ProfileCard";
import OptionsDiscoveryCard from "../components/options/OptionsDiscoveryCard";
import PaperDemoReadinessCard from "../components/demoReadiness/PaperDemoReadinessCard";
import { useI18n } from "../i18n/I18nContext";

// §B25 "Settings" (menu gauche + header) — section Compte réellement
// fonctionnelle (utilisateur courant, déconnexion, données réelles B05) ;
// le reste de l'écran liste honnêtement les réglages à venir plutôt que de
// fabriquer des contrôles qui n'agiraient sur rien (Telegram B21 — seul
// restant, voir ci-dessous).
// §B31 — le kill switch trading N'EST PLUS dans cette liste "à venir" : il
// est réel, retiré du tableau `upcoming` ci-dessous, et rendu via la vraie
// carte `KillSwitchCard` juste après la carte "Compte".
// §B10 (audit du 28/08) — même traitement pour la gouvernance IA : le
// contrat backend existait depuis B10 (D026) sans écran, retiré du tableau
// `upcoming`, rendu via `AiGovernanceCard` juste après le kill switch.
// §B09 — même traitement pour le catalogue des actifs : `AssetCatalogCard`
// juste après, "Catalogue des actifs" n'a jamais figuré dans `upcoming`
// (B09 était listé comme 0% "à faire" ailleurs dans AVANCEMENT.md, pas ici).
// §B30 — même traitement pour le profil d'expérience : `ProfileCard` juste
// après le catalogue des actifs, "Profil utilisateur étendu" retiré du
// tableau `upcoming`.
export default function SettingsPage() {
  const { t } = useI18n();
  const { user, onLogout } = useOutletContext<AppShellOutletContext>();

  const upcoming = [{ label: t("settings.telegramNotifications"), brick: "B21" }];

  return (
    <Box sx={{ maxWidth: 720 }}>
      <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
        {t("navigation.settings")}
      </Typography>

      <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
          {t("settings.account")}
        </Typography>
        <Typography>
          <strong>{user.display_name}</strong>
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          {user.email}
        </Typography>
        <Button variant="outlined" color="inherit" onClick={onLogout}>
          {t("header.signOut")}
        </Button>
      </Paper>

      <KillSwitchCard />

      <AiGovernanceCard />

      <AssetCatalogCard />

      <OptionsDiscoveryCard />

      <PaperDemoReadinessCard />

      <ProfileCard />

      <Paper variant="outlined" sx={{ p: 3 }}>
        <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
          {t("settings.upcoming")}
        </Typography>
        <List dense disablePadding>
          {upcoming.map((item, i) => (
            <Box key={item.label}>
              <ListItem disableGutters>
                <ListItemText primary={item.label} secondary={t("settings.availableWith", { brick: item.brick })} />
              </ListItem>
              {i < upcoming.length - 1 && <Divider component="li" />}
            </Box>
          ))}
        </List>
      </Paper>
    </Box>
  );
}
