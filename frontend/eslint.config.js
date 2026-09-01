// Config ESLint flat (B01, durcie en B25 comme annoncé par le commentaire
// d'origine). Deux changements : `tseslint.configs.recommended` ->
// `strict` (règles TypeScript plus strictes, ex. évite les assertions `as`
// non nécessaires) et ajout de `eslint-plugin-jsx-a11y` (§Qualité "Navigation
// clavier"/"Contrastes" — plutôt que de vérifier l'accessibilité seulement
// à l'œil pendant la vérification Playwright manuelle, ce plugin l'attrape
// automatiquement à chaque lint : labels manquants, rôles ARIA invalides,
// gestionnaires de clic sans équivalent clavier, etc.).
import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.strict, jsxA11y.flatConfigs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
);
