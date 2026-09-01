import { createContext } from "react";

// Objet React Context brut, séparé de `ThemeModeContext.tsx` (le composant
// `ThemeModeProvider`) et de `useThemeMode.ts` (le hook) — même raison que
// la séparation précédente : un fichier qui exporte un composant doit
// n'exporter QUE des composants pour que le Fast Refresh de Vite reste
// fiable (§lint react-refresh/only-export-components).

export type ThemeMode = "light" | "dark";

export type ThemeModeContextValue = {
  mode: ThemeMode;
  toggle: () => void;
};

export const ThemeModeContext = createContext<ThemeModeContextValue | null>(null);
