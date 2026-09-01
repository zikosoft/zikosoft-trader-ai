import { useEffect, useMemo, useState, type ReactNode } from "react";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { buildTheme } from "./theme";
import { ThemeModeContext, type ThemeMode, type ThemeModeContextValue } from "./themeModeContextObject";

// §B25 "Day/night" — état choisi une fois par onglet/appareil : préférence
// explicite mémorisée dans `localStorage` (survit à un rechargement), sinon
// déduite de `prefers-color-scheme` du système au tout premier chargement.
// §B25 "State management choisi et documenté" (décision D060, voir
// AVANCEMENT.md) : React Context + hooks natifs pour tout état transverse à
// l'app (thème ici, session/contexte d'exécution dans `App.tsx`) — pas de
// librairie externe (Redux/Zustand/Jotai). La donnée transverse réelle de
// cette V1 (utilisateur courant, contexte Replay/Paper actif, thème) reste
// petite et peu fréquemment modifiée ; les données volumineuses/spécifiques
// à un écran (ordres, positions, santé système…) restent des hooks locaux
// par page (`useLivePolling`), jamais poussées dans un store global — même
// principe de « ne pas construire une infrastructure dont le besoin réel
// n'est pas encore là » déjà appliqué ailleurs dans le projet.

const STORAGE_KEY = "zikosofttrader.theme-mode";

function readInitialMode(): ThemeMode {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // localStorage indisponible (navigation privée stricte, etc.) — repli
    // silencieux sur la préférence système ci-dessous.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(readInitialMode);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // Rien à faire — le mode reste actif pour cette session d'onglet,
      // simplement pas mémorisé pour la prochaine visite.
    }
  }, [mode]);

  const value = useMemo<ThemeModeContextValue>(
    () => ({ mode, toggle: () => setMode((m) => (m === "light" ? "dark" : "light")) }),
    [mode],
  );

  const theme = useMemo(() => buildTheme(mode), [mode]);

  return (
    <ThemeModeContext.Provider value={value}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ThemeModeContext.Provider>
  );
}
