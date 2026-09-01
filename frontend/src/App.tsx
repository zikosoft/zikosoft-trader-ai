import { lazy, Suspense, useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { Box, Container, LinearProgress, Skeleton, Typography } from "@mui/material";
import { fetchMe, logout, type User } from "./api/auth";
import { fetchContexts, type ContextListResponse } from "./api/context";
import { fetchOnboardingStatus, type OnboardingStatus } from "./api/onboarding";
import AppShell from "./AppShell";
import ContextChooser from "./ContextChooser";
import ContextSwitcher from "./ContextSwitcher";
import ErrorBoundary from "./ErrorBoundary";
import IncidentBanner from "./IncidentBanner";
import KillSwitchBanner from "./components/KillSwitchBanner";
import LoginForm from "./LoginForm";
import Onboarding from "./Onboarding";
import OverviewPage from "./pages/OverviewPage";
// §R29 (AVANCEMENT.md §38, observation posée en B25) — "candidat naturel :
// React.lazy() par route dans App.tsx une fois plusieurs pages lourdes
// construites (B26+), pas avant que le poids réel le justifie". B27
// (ECharts + TradingView Lightweight Charts) fait exactement grossir le
// bundle au-delà du seuil d'avertissement de Vite prédit par R29 (1,9 Mo
// minifié / 624 Ko gzippé avant ce changement) — le moment prédit est donc
// arrivé. `OverviewPage` reste EAGER (page d'accueil, route `index` ET
// route `*` de repli, toujours nécessaire immédiatement, et dépend déjà
// d'ECharts elle-même depuis B27 — rien à gagner à la rendre paresseuse).
// Toutes les autres pages ne se chargent qu'à la navigation réelle vers
// leur route.
const StrategiesPage = lazy(() => import("./pages/StrategiesPage"));
const AgentRoomPage = lazy(() => import("./pages/AgentRoomPage"));
const OrdersPage = lazy(() => import("./pages/OrdersPage"));
const PortfolioPage = lazy(() => import("./pages/PortfolioPage"));
const MarketPage = lazy(() => import("./pages/MarketPage"));
const ReplayPage = lazy(() => import("./pages/ReplayPage"));
const AlertsPage = lazy(() => import("./pages/AlertsPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const SystemHealthPage = lazy(() => import("./pages/SystemHealthPage"));

// §B25 — le shell applicatif complet (React + TypeScript + Material UI,
// routing, thèmes) remplace le placeholder qui annonçait "arrive en brique
// B25" depuis B01. Le séquencement de gating (connexion -> choix de
// contexte -> onboarding Alpaca si Paper -> app) reste EXACTEMENT celui
// posé par B05-B07 — seul ce qui s'affiche à chaque étape change
// d'habillage (Material UI) ; aucune étape ajoutée, aucune supprimée.

// §B25 "Error boundaries" : `<IncidentBanner />` reste HORS de la limite
// d'erreur — un incident système doit rester visible même si le reste du
// rendu React plante, l'un ne doit jamais pouvoir faire disparaître l'autre.
// §B31 — même raisonnement pour `<KillSwitchBanner />` : un trading
// suspendu doit rester visible même si le reste de l'app plante.
//
// §B31 bug trouvé pendant la vérification interactive — `id="zikosoft-banners"`
// sur ce wrapper est lu par `AppShell.tsx` (`document.getElementById`, même
// motif `ResizeObserver` que sa propre AppBar) pour décaler son AppBar
// `position: fixed` (sinon pinnée à `top: 0` quel que soit ce qui la
// précède dans le DOM) : sans ce décalage, un bandeau engagé se retrouvait
// visuellement en conflit avec l'AppBar, rendant le menu hamburger et tout
// le header inaccessibles tant qu'un bandeau était affiché (voir
// AppShell.tsx pour le détail complet). L'élément existe TOUJOURS (hauteur
// 0 si aucun bandeau) — y compris avant qu'AppShell ne soit monté (écran de
// connexion/onboarding), donc pas de condition de course.
export default function App() {
  return (
    <>
      <Box id="zikosoft-banners">
        <IncidentBanner />
        <KillSwitchBanner />
      </Box>
      <ErrorBoundary>
        <AppContent />
      </ErrorBoundary>
    </>
  );
}

function LoadingScreen() {
  return (
    <Container maxWidth="sm" sx={{ py: 8 }}>
      <Skeleton variant="text" width="60%" height={40} sx={{ mb: 2 }} />
      <Skeleton variant="rectangular" height={120} sx={{ mb: 1, borderRadius: 1 }} />
      <Skeleton variant="text" width="80%" />
      <Skeleton variant="text" width="40%" />
    </Container>
  );
}

function AppContent() {
  const [user, setUser] = useState<User | null | undefined>(undefined); // undefined = pas encore vérifié
  const [contextState, setContextState] = useState<ContextListResponse | null | undefined>(
    undefined, // undefined = pas encore chargé, null = erreur de chargement
  );
  const [onboarding, setOnboarding] = useState<OnboardingStatus | null | undefined>(undefined);

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    if (!user) return; // /api/contexts exige une session (B06 protégé comme toute route métier)
    fetchContexts()
      .then(setContextState)
      .catch(() => setContextState(null));
  }, [user]);

  useEffect(() => {
    // §B07 "Bloquer le dashboard Paper sans compte valide" : on ne charge
    // (et n'exige) l'onboarding Alpaca que si Paper est le contexte actif —
    // Replay n'en a jamais besoin.
    if (contextState?.active_kind !== "PAPER") return;
    fetchOnboardingStatus()
      .then(setOnboarding)
      .catch(() => setOnboarding(null));
  }, [contextState?.active_kind]);

  if (user === undefined) {
    return <LoadingScreen />;
  }

  if (user === null) {
    return <LoginForm onLoggedIn={setUser} />;
  }

  if (contextState === undefined) {
    return <LoadingScreen />;
  }

  if (contextState === null) {
    return (
      <Container maxWidth="sm" sx={{ py: 8 }}>
        <Typography color="error">
          Impossible de charger les contextes Replay/Paper — vérifie que le backend répond.
        </Typography>
      </Container>
    );
  }

  if (contextState.active_kind === null) {
    return <ContextChooser onSelected={setContextState} />;
  }

  const paperNotConnected =
    contextState.active_kind === "PAPER" &&
    (onboarding === undefined || onboarding?.account?.status !== "connected");

  if (paperNotConnected) {
    if (onboarding === undefined) {
      return <LoadingScreen />;
    }
    return (
      <Box>
        {/* Le sélecteur de contexte reste accessible pendant l'onboarding
            (permet de revenir en Replay sans terminer la connexion Alpaca,
            comportement inchangé depuis B06/B07) — le shell complet (menu +
            header, §B25) n'existe qu'UNE FOIS l'onboarding terminé, donc ce
            sélecteur est affiché ici directement plutôt que via AppShell. */}
        <Container maxWidth="sm" sx={{ pt: 2 }}>
          <ContextSwitcher state={contextState} onChanged={setContextState} />
        </Container>
        <Onboarding onConnected={setOnboarding} />
      </Box>
    );
  }

  function handleLogout() {
    logout().then(() => setUser(null));
  }

  return (
    <Suspense fallback={<LinearProgress />}>
      <Routes>
        <Route
          element={
            <AppShell
              user={user}
              contextState={contextState}
              onContextChanged={setContextState}
              onLogout={handleLogout}
            />
          }
        >
          <Route index element={<OverviewPage />} />
          <Route path="strategies" element={<StrategiesPage />} />
          <Route path="agent-room" element={<AgentRoomPage />} />
          <Route path="orders" element={<OrdersPage />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="market" element={<MarketPage />} />
          <Route path="replay" element={<ReplayPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="system-health" element={<SystemHealthPage />} />
          <Route path="*" element={<OverviewPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
