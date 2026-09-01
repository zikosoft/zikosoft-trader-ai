import { useContext } from "react";
import { ThemeModeContext, type ThemeModeContextValue } from "./themeModeContextObject";

// Séparé de `ThemeModeContext.tsx` (§lint react-refresh/only-export-components)
// — un fichier qui exporte un composant (`ThemeModeProvider`) doit
// n'exporter QUE des composants pour que le Fast Refresh de Vite reste
// fiable ; ce hook vit donc à part, comme `context`/`onboarding` séparent
// déjà leurs types de leurs fonctions dans `api/*.ts`.
export function useThemeMode(): ThemeModeContextValue {
  const ctx = useContext(ThemeModeContext);
  if (!ctx) throw new Error("useThemeMode doit être utilisé sous ThemeModeProvider");
  return ctx;
}
