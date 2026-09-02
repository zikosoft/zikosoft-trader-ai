import { useEffect, useRef, useState } from "react";
import { Link as RouterLink, Outlet, useLocation } from "react-router-dom";
import Brightness4Icon from "@mui/icons-material/Brightness4";
import Brightness7Icon from "@mui/icons-material/Brightness7";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DashboardIcon from "@mui/icons-material/Dashboard";
import ForumIcon from "@mui/icons-material/Forum";
import HealthAndSafetyIcon from "@mui/icons-material/HealthAndSafety";
import MenuIcon from "@mui/icons-material/Menu";
import NotificationsIcon from "@mui/icons-material/Notifications";
import ReceiptLongIcon from "@mui/icons-material/ReceiptLong";
import ReplayIcon from "@mui/icons-material/Replay";
import RuleIcon from "@mui/icons-material/Rule";
import SettingsIcon from "@mui/icons-material/Settings";
import ShowChartIcon from "@mui/icons-material/ShowChart";
import AccountBalanceWalletIcon from "@mui/icons-material/AccountBalanceWallet";
import LogoutIcon from "@mui/icons-material/Logout";
import {
  AppBar,
  Avatar,
  Badge,
  Box,
  Chip,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  Menu,
  MenuItem,
  Toolbar,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import type { User } from "./api/auth";
import { fetchSystemHealth } from "./api/systemHealth";
import { fetchUnreadAlertCount } from "./api/alerts";
import type { ContextListResponse } from "./api/context";
import { AgentRoomProvider } from "./AgentRoomContext";
import AgentRoomDivider from "./components/agentRoom/AgentRoomDivider";
import AgentRoomLauncher from "./components/agentRoom/AgentRoomLauncher";
import AgentRoomPanel from "./components/agentRoom/AgentRoomPanel";
import ContextSwitcher from "./ContextSwitcher";
import { useAgentRoom } from "./useAgentRoom";
import { useLivePolling } from "./hooks/useLivePolling";
import { useThemeMode } from "./useThemeMode";
import { SUPPORTED_LOCALES } from "./i18n/config";
import { useI18n } from "./i18n/I18nContext";

// §B25 — coquille applicative complète (menu gauche + header + zone de
// contenu routée). Construit UNE FOIS que l'utilisateur est connecté, a un
// contexte Replay/Paper actif, et (si Paper) un compte Alpaca connecté —
// `App.tsx` garde la responsabilité de ce séquencement, inchangée depuis
// B05-B07.

export type AppShellOutletContext = {
  user: User;
  onLogout: () => void;
  // §B26 "CTA Launch Replay" — le dashboard sans activité a besoin de
  // pouvoir déclencher un vrai changement de contexte (même action que
  // `ContextSwitcher.tsx`, B06), pas juste naviguer vers un écran. Ajouté
  // ici plutôt que dupliqué : une seule source de vérité pour l'état de
  // contexte, comme le reste du shell.
  contextState: ContextListResponse;
  onContextChanged: (state: ContextListResponse) => void;
};

type NavItem = { labelKey: string; path: string; icon: React.ReactNode };

const NAV_ITEMS: NavItem[] = [
  { labelKey: "navigation.overview", path: "/", icon: <DashboardIcon /> },
  { labelKey: "navigation.strategies", path: "/strategies", icon: <RuleIcon /> },
  { labelKey: "navigation.agentRoom", path: "/agent-room", icon: <ForumIcon /> },
  { labelKey: "navigation.orders", path: "/orders", icon: <ReceiptLongIcon /> },
  { labelKey: "navigation.portfolio", path: "/portfolio", icon: <AccountBalanceWalletIcon /> },
  { labelKey: "navigation.market", path: "/market", icon: <ShowChartIcon /> },
  { labelKey: "navigation.replay", path: "/replay", icon: <ReplayIcon /> },
  { labelKey: "navigation.alerts", path: "/alerts", icon: <NotificationsIcon /> },
  { labelKey: "navigation.settings", path: "/settings", icon: <SettingsIcon /> },
  { labelKey: "navigation.systemHealth", path: "/system-health", icon: <HealthAndSafetyIcon /> },
];

const DRAWER_WIDTH_EXPANDED = 240;
const DRAWER_WIDTH_COLLAPSED = 64;
const COLLAPSE_STORAGE_KEY = "zikosofttrader.sidebar-collapsed";

function readInitialCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

type Props = {
  user: User;
  contextState: ContextListResponse;
  onContextChanged: (state: ContextListResponse) => void;
  onLogout: () => void;
};

// §B28 "Agent Room" (D010/D011 : trois modes, ne pas bloquer le dashboard) —
// le panneau doit exister GLOBALEMENT, quelle que soit la route affichée
// (voir `pages/AgentRoomPage.tsx`, réduit à un simple déclencheur), donc le
// Provider englobe tout le shell plutôt que d'être monté route par route.
export default function AppShell(props: Props) {
  return (
    <AgentRoomProvider>
      <AppShellInner {...props} />
    </AgentRoomProvider>
  );
}

function AppShellInner({ user, contextState, onContextChanged, onLogout }: Props) {
  const { locale, setLocale, t } = useI18n();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const location = useLocation();
  const { mode, toggle: toggleThemeMode } = useThemeMode();

  const [collapsed, setCollapsed] = useState(readInitialCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenuAnchor, setUserMenuAnchor] = useState<null | HTMLElement>(null);

  // §B28 — mode/ouverture viennent du contexte global (voir
  // `AgentRoomContext.tsx`) ; seule la largeur du panneau docké (glissée
  // localement via `AgentRoomDivider`) reste un état propre à ce shell,
  // volontairement pas persistée (seul le MODE l'est, §checklist "préférence
  // sauvegardée").
  const { mode: roomMode, open: roomOpen, closeRoom } = useAgentRoom();
  const [dockedPercent, setDockedPercent] = useState(35);
  const mainRowRef = useRef<HTMLDivElement>(null);

  const dockedActive = roomOpen && roomMode === "docked" && !isMobile;
  const fullscreenActive = roomOpen && roomMode === "fullscreen" && !isMobile;
  // §checklist "mobile bascule en plein écran/bottom sheet" — docked n'a pas
  // de sens sur un écran étroit (pas de place pour un 65/35), donc les deux
  // modes non-compact convergent vers la même feuille du bas sur mobile.
  const mobileSheetActive = roomOpen && roomMode !== "compact" && isMobile;

  function setCollapsedPersisted(value: boolean) {
    setCollapsed(value);
    try {
      window.localStorage.setItem(COLLAPSE_STORAGE_KEY, value ? "1" : "0");
    } catch {
      // Rien à faire — le repli reste actif pour cette session d'onglet.
    }
  }

  // §checklist "Santé globale" (header) — même route que la page System
  // Health et le bandeau d'incident (B22/B23), même cadence de poll.
  const { data: health } = useLivePolling(fetchSystemHealth, 5000);
  const overallOk = health ? Object.values(health.checks).every((c) => c.status !== "DEGRADED" && c.status !== "DISCONNECTED") : null;

  // §B20 "Compteur dans le header" — poll léger, même cadence que le
  // reste des indicateurs de header (D058 : polling, pas de transport
  // temps réel). `data` reste `null` tant qu'aucun contexte n'est actif
  // (onboarding en cours) — `unreadCount` retombe alors honnêtement à 0
  // plutôt que d'afficher une erreur dans le badge.
  const { data: unreadAlerts } = useLivePolling(fetchUnreadAlertCount, 10000);
  const unreadCount = unreadAlerts?.unread_count ?? 0;

  const drawerWidth = collapsed ? DRAWER_WIDTH_COLLAPSED : DRAWER_WIDTH_EXPANDED;

  // §Qualité "Mobile/tablette/desktop" — l'AppBar a une hauteur VARIABLE
  // (une ligne sur desktop/tablette, deux sur mobile — et la seconde peut
  // elle-même s'enrouler sur plusieurs lignes selon la largeur exacte de
  // l'écran et le libellé du contexte actif). Un espaceur `<Toolbar />` à
  // hauteur fixe supposait à tort une hauteur constante — repéré pendant la
  // vérification Playwright responsive ("Overview" caché sous l'AppBar sur
  // mobile). Mesurée en direct via `ResizeObserver` plutôt que supposée,
  // et réutilisée pour le contenu principal ET le tiroir de navigation.
  const appBarRef = useRef<HTMLDivElement>(null);
  const [appBarHeight, setAppBarHeight] = useState(64);

  useEffect(() => {
    const el = appBarRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const height = entries[0]?.contentRect.height;
      if (height) setAppBarHeight(height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // §B31 bug trouvé pendant la vérification interactive — `IncidentBanner`
  // (B23) et `KillSwitchBanner` (B31) sont montés dans `App.tsx`, HORS de
  // `AppShell` (nécessaire : ils doivent rester visibles même sur l'écran de
  // connexion/onboarding, avant qu'AppShell n'existe — voir App.tsx). Mais
  // l'AppBar ci-dessous est `position: fixed` sans AUCUN offset — pinné à
  // `top: 0` du viewport quel que soit ce qui le précède dans le flux DOM.
  // Un bandeau engagé (kill switch OU incident) se retrouvait donc
  // physiquement recouvert PAR l'AppBar (même z-index explicite plus élevé
  // sur `KillSwitchBanner`, l'AppBar restait cliquable/visuel au-dessus par
  // endroits selon la variante) — ou, sans z-index sur le bandeau,
  // l'inverse : l'AppBar (z-index explicite) recouvrait le bandeau, rendant
  // le menu hamburger (mobile) et tout le header INACCESSIBLES tant qu'un
  // bandeau était affiché. Repéré en capturant `/settings` avec le kill
  // switch engagé (mobile 390px) : l'AppBar avait purement disparu de la
  // capture, recouverte par le bandeau rouge plein écran.
  //
  // Correctif : mesurer la hauteur réelle du conteneur de bandeaux
  // (`#zikosoft-banners`, voir App.tsx) avec le MÊME motif ResizeObserver
  // que l'AppBar ci-dessus, décaler l'AppBar elle-même de cette hauteur
  // (`top`, voir plus bas — passé en chaîne `"...px"`, jamais en nombre brut,
  // même piège documenté plus bas pour l'overlay plein écran), et utiliser
  // `headerOffset` (= AppBar + bandeaux) UNIQUEMENT pour l'espaceur du
  // tiroir de navigation : son `.MuiDrawer-paper` est LUI AUSSI
  // `position: fixed` (comme l'AppBar), donc ignore tout ce qui le précède
  // dans le flux DOM et a besoin du décalage COMPLET depuis le vrai haut du
  // viewport. Les autres espaceurs "pousser le contenu sous le header"
  // (contenu principal, panneau docké) restent volontairement en
  // `appBarHeight` BRUT (pas `headerOffset`) : leurs conteneurs vivent en
  // flux NORMAL, donc leur propre coin haut-gauche est déjà décalé de
  // `bannerHeight` par le flux du DOM lui-même (`#zikosoft-banners` les
  // précède) — utiliser `headerOffset` là aurait additionné `bannerHeight`
  // une seconde fois (bug trouvé puis corrigé pendant cette même
  // vérification interactive : "Overview" se retrouvait décalé d'un
  // bandeau entier de trop sous une AppBar pourtant déjà bien positionnée —
  // voir les commentaires sur ces deux espaceurs plus bas). Le conteneur de
  // bandeaux existe TOUJOURS dans le DOM (hauteur 0 si aucun bandeau) — pas
  // de condition de course avec le montage d'AppShell.
  //
  // Volontairement PAS étendu aux calculs `100vh - appBarHeight` du mode
  // plein écran/docké de l'Agent Room (overlay `top`, `minHeight`/`height`
  // liés au viewport) : ce sont des calculs approximatifs déjà tolérés tels
  // quels avant B31 (vérifiés par la vérification interactive B28, jamais
  // exacts au pixel près — `minHeight`/`height` y jouent un rôle défensif
  // avec le stretch flexbox, pas un ancrage pixel-parfait) et OUT OF SCOPE
  // pour B31 : la combinaison "bandeau affiché + Agent Room plein écran ou
  // docké" est un cas marginal, et toucher ces calculs sous pression de
  // livraison sans re-vérifier l'intégralité du mode Agent Room (posé et
  // durci sur plusieurs itérations Playwright en B28) aurait été plus
  // risqué que bénéfique. Limitation documentée dans AVANCEMENT.md plutôt
  // que corrigée à l'aveugle.
  const [bannerHeight, setBannerHeight] = useState(0);

  useEffect(() => {
    const el = document.getElementById("zikosoft-banners");
    if (!el) return;
    setBannerHeight(el.getBoundingClientRect().height);
    const observer = new ResizeObserver((entries) => {
      const height = entries[0]?.contentRect.height;
      setBannerHeight(height ?? 0);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const headerOffset = appBarHeight + bannerHeight;

  const drawerContent = (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Box sx={{ height: headerOffset, flexShrink: 0 }} />
      <List sx={{ flex: 1 }}>
        {NAV_ITEMS.map((item) => {
          const active = location.pathname === item.path;
          const label = t(item.labelKey);
          const button = (
            <ListItemButton
              key={item.path}
              component={RouterLink}
              to={item.path}
              selected={active}
              onClick={() => setMobileOpen(false)}
              sx={{ justifyContent: collapsed && !isMobile ? "center" : "flex-start", px: 2.5 }}
            >
              <ListItemIcon sx={{ minWidth: collapsed && !isMobile ? 0 : 40, justifyContent: "center" }}>
                {item.icon}
              </ListItemIcon>
              {(!collapsed || isMobile) && <ListItemText primary={label} />}
            </ListItemButton>
          );
          return collapsed && !isMobile ? (
            <Tooltip key={item.path} title={label} placement="right">
              {button}
            </Tooltip>
          ) : (
            button
          );
        })}
      </List>
      {!isMobile && (
        <Box sx={{ p: 1, display: "flex", justifyContent: "center", borderTop: 1, borderColor: "divider" }}>
          <IconButton onClick={() => setCollapsedPersisted(!collapsed)} size="small" aria-label={t("header.collapseMenu")}>
            {collapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
          </IconButton>
        </Box>
      )}
    </Box>
  );

  return (
    <Box sx={{ display: "flex" }}>
      <AppBar ref={appBarRef} position="fixed" sx={{ top: `${bannerHeight}px`, zIndex: theme.zIndex.drawer + 1 }}>
        <Toolbar sx={{ gap: 2 }}>
          {isMobile && (
            <IconButton color="inherit" edge="start" onClick={() => setMobileOpen(true)} aria-label={t("header.openMenu")}>
              <MenuIcon />
            </IconButton>
          )}
          <Typography variant="h6" component="div" sx={{ whiteSpace: "nowrap" }}>
            ZikosoftTrader AI
          </Typography>

          {/* §Qualité "Mobile/tablette/desktop" — la ligne d'origine (titre +
              sélecteur de contexte + indicateurs + menu utilisateur, tout sur
              une seule Toolbar) débordait hors écran sur un mobile étroit
              (~390px) : le sélecteur de contexte ET l'avatar se retrouvaient
              partiellement/totalement hors viewport, découvert pendant la
              vérification Playwright responsive (voir AVANCEMENT.md). Sur
              desktop/tablette (`!isMobile`), tout reste sur cette même ligne
              ; sur mobile, seul l'avatar (menu utilisateur) reste ici — le
              reste (contexte, santé, alertes, thème) passe sur une seconde
              ligne dédiée juste en dessous, qui peut s'enrouler
              (`flexWrap`) au lieu de déborder. */}
          {!isMobile && (
            <Box sx={{ flex: 1, display: "flex", justifyContent: "center" }}>
              <ContextSwitcher state={contextState} onChanged={onContextChanged} />
            </Box>
          )}

          <Box sx={{ flex: isMobile ? 1 : undefined, display: "flex", alignItems: "center", gap: 1, justifyContent: "flex-end" }}>
            {!isMobile && (
              <HeaderIndicators overallOk={overallOk} unreadCount={unreadCount} mode={mode} onToggleTheme={toggleThemeMode} />
            )}

            <Tooltip title={user.display_name}>
              <IconButton onClick={(e) => setUserMenuAnchor(e.currentTarget)} aria-label={t("header.userMenu")}>
                <Avatar sx={{ width: 32, height: 32, fontSize: "0.9rem" }}>
                  {user.display_name.slice(0, 1).toUpperCase()}
                </Avatar>
              </IconButton>
            </Tooltip>
            <Menu anchorEl={userMenuAnchor} open={Boolean(userMenuAnchor)} onClose={() => setUserMenuAnchor(null)}>
              <MenuItem
                component={RouterLink}
                to="/settings"
                onClick={() => setUserMenuAnchor(null)}
              >
                <ListItemIcon>
                  <SettingsIcon fontSize="small" />
                </ListItemIcon>
                {t("navigation.settings")}
              </MenuItem>
              <Divider />
              <ListSubheader disableSticky sx={{ lineHeight: "32px", fontSize: "0.75rem", fontWeight: 700 }}>
                {t("language.menuTitle")}
              </ListSubheader>
              {SUPPORTED_LOCALES.map((language) => (
                <MenuItem
                  key={language.code}
                  selected={locale === language.code}
                  onClick={() => {
                    setLocale(language.code);
                    setUserMenuAnchor(null);
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    <span role="img" aria-label={t(`language.${language.code}`)}>{language.flag}</span>
                  </ListItemIcon>
                  <ListItemText primary={language.nativeName} />
                </MenuItem>
              ))}
              <Divider />
              <MenuItem
                onClick={() => {
                  setUserMenuAnchor(null);
                  onLogout();
                }}
              >
                <ListItemIcon>
                  <LogoutIcon fontSize="small" />
                </ListItemIcon>
                {t("header.signOut")}
              </MenuItem>
            </Menu>
          </Box>
        </Toolbar>

        {isMobile && (
          <Toolbar
            variant="dense"
            sx={{ gap: 1, flexWrap: "wrap", py: 0.5, borderTop: 1, borderColor: "rgba(255,255,255,0.2)" }}
          >
            <ContextSwitcher state={contextState} onChanged={onContextChanged} />
            <Box sx={{ flex: 1 }} />
            <HeaderIndicators overallOk={overallOk} unreadCount={unreadCount} mode={mode} onToggleTheme={toggleThemeMode} />
          </Toolbar>
        )}
      </AppBar>

      <Box component="nav" sx={{ width: { sm: drawerWidth }, flexShrink: { sm: 0 } }}>
        {isMobile ? (
          <Drawer
            variant="temporary"
            open={mobileOpen}
            onClose={() => setMobileOpen(false)}
            ModalProps={{ keepMounted: true }}
            sx={{ "& .MuiDrawer-paper": { width: DRAWER_WIDTH_EXPANDED } }}
          >
            {drawerContent}
          </Drawer>
        ) : (
          <Drawer
            variant="permanent"
            open
            sx={{
              "& .MuiDrawer-paper": {
                width: drawerWidth,
                overflowX: "hidden",
                transition: theme.transitions.create("width", { duration: theme.transitions.duration.shortest }),
              },
            }}
          >
            {drawerContent}
          </Drawer>
        )}
      </Box>

      <Box
        component="main"
        ref={mainRowRef}
        sx={{ flexGrow: 1, width: { sm: `calc(100% - ${drawerWidth}px)` }, display: "flex", flexDirection: "row", minWidth: 0 }}
      >
        <Box
          sx={{
            flex: dockedActive ? `0 0 ${100 - dockedPercent}%` : 1,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            position: "relative",
            // §Playwright (vérification B28) — un `minHeight` lié au
            // viewport (comme le panneau docké sticky ci-dessous) est
            // nécessaire pour que l'overlay plein écran ci-dessous puisse
            // s'ancrer avec `bottom: 0` : sans ça, la hauteur de CE
            // conteneur dépend de son contenu statique (l'Outlet, souvent
            // vide sur `/agent-room`), et l'overlay se retrouverait
            // rabougri à une hauteur quasi nulle au lieu de couvrir tout
            // l'écran. Un `minHeight` (pas `height`) laisse les pages au
            // contenu réellement plus long que l'écran défiler normalement.
            minHeight: `calc(100vh - ${appBarHeight}px)`,
          }}
        >
          {/* §B31 — RAW `appBarHeight` ici, PAS `headerOffset` : contrairement
              au tiroir de navigation ci-dessus (dont le `.MuiDrawer-paper`
              est `position: fixed`, donc ignore tout ce qui le précède dans
              le flux DOM), CE conteneur (`component="main"` plus haut) reste
              en flux NORMAL — son propre coin haut-gauche démarre déjà à
              `bannerHeight` px du haut du viewport, simplement parce que
              `#zikosoft-banners` (voir App.tsx) le précède dans le DOM et
              occupe une vraie hauteur de flux. Utiliser `headerOffset` ici
              aurait ADDITIONNÉ `bannerHeight` une seconde fois (repéré via
              inspection DOM pendant la vérification interactive : "Overview"
              se retrouvait décalé d'un bandeau entier de trop sous l'AppBar,
              alors que l'AppBar elle-même était déjà correctement positionnée). */}
          <Box sx={{ height: appBarHeight, flexShrink: 0 }} />
          <Box sx={{ flex: 1, minHeight: 0, p: 3 }}>
            {/* §bug corrigé pendant la vérification Playwright B28 —
                l'Outlet (donc `AgentRoomPage.tsx`) DOIT rester monté en
                permanence tant qu'on est sur cette route : le remplacer
                conditionnellement par `<AgentRoomPanel />` le démontait en
                mode plein écran, et le REMONTAIT dès qu'on changeait de
                mode (docked/compact) — ce qui rejouait l'effet "au montage"
                de `AgentRoomPage` (`openRoom("fullscreen")`) et ramenait
                instantanément en plein écran, rendant les deux autres modes
                inaccessibles depuis cette route. Un overlay superposé (pas
                un remplacement) garde l'Outlet monté en continu. */}
            <Outlet
              context={{ user, onLogout, contextState, onContextChanged } satisfies AppShellOutletContext}
            />
          </Box>
          {fullscreenActive && (
            // §checklist "mode Full screen central... panneau couvre toute
            // la zone de contenu" — l'AppBar et le menu latéral restent
            // visibles (D010/D011 "ne pas bloquer le dashboard" = ne jamais
            // masquer la navigation elle-même), seule cette zone de contenu
            // est recouverte.
            <Box
              sx={{
                position: "absolute",
                // §bug corrigé pendant la vérification Playwright B28 —
                // `top`/`left`/`right`/`bottom` font partie du système
                // d'espacement `sx` de MUI : un NOMBRE brut y est multiplié
                // par `theme.spacing(1)` (8px par défaut), exactement comme
                // `margin`/`padding` — PAS traité comme un pixel direct
                // (contrairement à `width`/`height`, qui eux ne sont pas
                // concernés). `appBarHeight` (mesuré en pixels réels via
                // ResizeObserver, voir plus haut) doit donc être passé en
                // chaîne `"...px"` ici, jamais en nombre brut, sous peine
                // d'un panneau ancré à 8× la hauteur réelle de l'AppBar.
                top: `${appBarHeight}px`,
                left: 0,
                right: 0,
                bottom: 0,
                bgcolor: "background.default",
                zIndex: 2,
                display: "flex",
                flexDirection: "column",
              }}
            >
              <AgentRoomPanel />
            </Box>
          )}
        </Box>

        {dockedActive && (
          // §checklist "mode Docked... divider redimensionnable" — deux bugs
          // rencontrés pendant la vérification Playwright B28 :
          // 1) `position: sticky` ici ne s'accrochait pas de façon fiable
          //    (la page `/agent-room` est plus courte que le viewport, donc
          //    rien ne "scrolle" jamais pour déclencher l'ancrage) ;
          // 2) `minHeight: 0` seul (sans `height` explicite) NE DONNE PAS
          //    une hauteur définie à ce conteneur — `align-items: stretch`
          //    (par défaut sur la ligne flex `main`) ne peut étirer un item
          //    que si le CONTENEUR lui-même a une hauteur résolue, ce qui
          //    n'était pas le cas ici (hauteur "auto" = poussée par son
          //    propre contenu). Conséquence concrète : le fil du Live
          //    Debate (`overflow-y: auto` dans `LiveDebateTab.tsx`) n'avait
          //    jamais de hauteur bornée à faire défiler — il s'étirait à sa
          //    hauteur de contenu NATURELLE (tous les messages empilés,
          //    ~1580px avec les données de test), gonflant toute la page
          //    (`document.body.scrollHeight` mesuré à ~1729px) au lieu de
          //    rester dans son panneau de ~836px avec défilement interne.
          // Une hauteur EXPLICITE (comme la colonne de gauche l'impose déjà
          // via `minHeight`, mais ici en vrai `height` pour établir un
          // ancrage définitif) résout les deux à la fois, sans sticky ni
          // calcul de scroll.
          <Box
            sx={{
              display: "flex",
              flexShrink: 0,
              flexBasis: `${dockedPercent}%`,
              height: `calc(100vh - ${appBarHeight}px)`,
            }}
          >
            <AgentRoomDivider panelPercent={dockedPercent} onChange={setDockedPercent} containerRef={mainRowRef} />
            <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", borderLeft: 1, borderColor: "divider", bgcolor: "background.paper" }}>
              {/* §B31 — même raison que le spacer du contenu principal
                  ci-dessus : `appBarHeight` RAW, pas `headerOffset` — ce
                  panneau docké vit lui aussi en flux normal à l'intérieur de
                  `component="main"`, déjà décalé de `bannerHeight` par le
                  flux du DOM. */}
              <Box sx={{ height: appBarHeight, flexShrink: 0 }} />
              <Box sx={{ flex: 1, minHeight: 0 }}>
                <AgentRoomPanel />
              </Box>
            </Box>
          </Box>
        )}
      </Box>

      {mobileSheetActive && (
        // §bug corrigé pendant la vérification Playwright B28 (capture
        // mobile) — sans `zIndex` explicite ici, le haut de cette feuille
        // (son en-tête "AI Agent Room" + boutons de mode + fermeture)
        // rendait SOUS l'AppBar mobile à deux lignes (contexte + santé/
        // thème, §B25) plutôt qu'au-dessus, le rendant invisible/
        // inaccessible — seuls les onglets, plus bas, dépassaient de sous
        // l'AppBar. Un `zIndex` supérieur à celui de l'AppBar
        // (`theme.zIndex.drawer + 1`) force cette feuille au-dessus, comme
        // le lanceur flottant (`AgentRoomLauncher.tsx`, `drawer + 2`).
        <Drawer
          anchor="bottom"
          open
          onClose={closeRoom}
          sx={{ zIndex: (theme) => theme.zIndex.drawer + 2 }}
          slotProps={{ paper: { sx: { height: "85vh", display: "flex", flexDirection: "column" } } }}
        >
          <AgentRoomPanel />
        </Drawer>
      )}

      <AgentRoomLauncher />
    </Box>
  );
}

function HeaderIndicators({
  overallOk,
  unreadCount,
  mode,
  onToggleTheme,
}: {
  overallOk: boolean | null;
  unreadCount: number;
  mode: "light" | "dark";
  onToggleTheme: () => void;
}) {
  const { t } = useI18n();
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      {overallOk !== null && (
        <Tooltip title={t("header.globalHealth")}>
          <Chip
            component={RouterLink}
            to="/system-health"
            clickable
            size="small"
            label={overallOk ? t("header.healthOk") : t("header.healthIncident")}
            color={overallOk ? "success" : "error"}
            sx={{ color: "#fff" }}
          />
        </Tooltip>
      )}

      <Tooltip title={t("header.alerts")}>
        <IconButton component={RouterLink} to="/alerts" color="inherit">
          <Badge badgeContent={unreadCount} color="error" max={99}>
            <NotificationsIcon />
          </Badge>
        </IconButton>
      </Tooltip>

      <Tooltip title={mode === "dark" ? t("header.switchToLight") : t("header.switchToDark")}>
        <IconButton color="inherit" onClick={onToggleTheme} aria-label={t("header.toggleTheme")}>
          {mode === "dark" ? <Brightness7Icon /> : <Brightness4Icon />}
        </IconButton>
      </Tooltip>
    </Box>
  );
}
