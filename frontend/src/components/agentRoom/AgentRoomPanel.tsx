import type { ReactNode } from "react";
import { Box, IconButton, Tab, Tabs, Tooltip, Typography } from "@mui/material";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutlineOutlined";
import CloseIcon from "@mui/icons-material/Close";
import OpenInFullIcon from "@mui/icons-material/OpenInFull";
import ViewSidebarIcon from "@mui/icons-material/ViewSidebar";
import type { AgentRoomMode } from "../../agentRoomContextObject";
import { useAgentRoom } from "../../useAgentRoom";
import AskZikoTab from "./AskZikoTab";
import DecisionDetailsTab from "./DecisionDetailsTab";
import LiveDebateTab from "./LiveDebateTab";
import { useI18n } from "../../i18n/I18nContext";

// §B28 checklist "trois modes... boutons toujours accessibles" — le
// contenu (en-tête + boutons de mode + les 3 onglets) est IDENTIQUE quel
// que soit le mode d'affichage ; seul le conteneur qui l'englobe change de
// taille/position (voir `AppShell.tsx`) — c'est ce composant qui rend les 3
// modes réellement interchangeables plutôt que 3 UIs différentes.

const MODE_META: Record<AgentRoomMode, { icon: ReactNode; labelKey: string }> = {
  compact: { icon: <ChatBubbleOutlineIcon fontSize="small" />, labelKey: "agentRoom.mode.compact" },
  docked: { icon: <ViewSidebarIcon fontSize="small" />, labelKey: "agentRoom.mode.docked" },
  fullscreen: { icon: <OpenInFullIcon fontSize="small" />, labelKey: "agentRoom.mode.fullscreen" },
};

const MODE_ORDER: AgentRoomMode[] = ["compact", "docked", "fullscreen"];

type Props = {
  dense?: boolean;
  // Le sélecteur de mode n'a de sens que quand le panneau appartient à
  // l'AppShell (desktop) — sur mobile, le panneau est déjà une feuille
  // plein écran (Drawer bottom) où "changer de mode" n'aurait pas de sens
  // visuel ; voir `AppShell.tsx`.
  showModeSwitch?: boolean;
};

export default function AgentRoomPanel({ dense = false, showModeSwitch = true }: Props) {
  const { t } = useI18n();
  const { mode, setMode, activeTab, setActiveTab, closeRoom } = useAgentRoom();

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, px: 1, py: 0.5, borderBottom: 1, borderColor: "divider" }}>
        <Typography variant={dense ? "caption" : "subtitle2"} sx={{ flex: 1, fontWeight: 700 }}>
          AI Agent Room
        </Typography>
        {showModeSwitch &&
          MODE_ORDER.map((m) => (
            <Tooltip key={m} title={t(MODE_META[m].labelKey)}>
              <IconButton size="small" color={mode === m ? "primary" : "default"} onClick={() => setMode(m)} aria-label={t(MODE_META[m].labelKey)}>
                {MODE_META[m].icon}
              </IconButton>
            </Tooltip>
          ))}
        <Tooltip title={t("common.close")}>
          <IconButton size="small" onClick={closeRoom} aria-label={t("agentRoom.close")}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      <Tabs
        value={activeTab}
        onChange={(_, value) => setActiveTab(value)}
        variant="fullWidth"
        sx={{ minHeight: dense ? 32 : 48 }}
      >
        <Tab value="live" label={t("agentRoom.liveDebate")} sx={{ minHeight: dense ? 32 : 48, fontSize: dense ? "0.65rem" : undefined }} />
        <Tab value="ask" label={t("agentRoom.askZiko")} sx={{ minHeight: dense ? 32 : 48, fontSize: dense ? "0.65rem" : undefined }} />
        <Tab value="decision" label={t("agentRoom.decisionDetails")} sx={{ minHeight: dense ? 32 : 48, fontSize: dense ? "0.65rem" : undefined }} />
      </Tabs>

      <Box sx={{ flex: 1, minHeight: 0 }}>
        {activeTab === "live" && <LiveDebateTab dense={dense} />}
        {activeTab === "ask" && <AskZikoTab dense={dense} />}
        {activeTab === "decision" && <DecisionDetailsTab dense={dense} />}
      </Box>
    </Box>
  );
}
