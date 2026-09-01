import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Squelette (B01-B04 + proxy API ajouté en B05). Sans ce proxy, les appels
// fetch("/api/...") du navigateur visent http://localhost:5173/api/... —
// qui n'existe pas côté serveur de dev Vite, seulement les assets frontend.
// Le proxy fait apparaître /api comme same-origin pour le navigateur (et
// laisse donc passer le cookie de session B05 sans souci CORS), tout en
// forwardant réellement vers backend-api. Cible configurable : à l'intérieur
// de Docker Compose, VITE_API_PROXY_TARGET=http://backend-api:8000 (voir
// .env.example) ; en dev local hors Docker (`npm run dev` avec un
// backend-api lancé à la main), la valeur par défaut vise localhost:8000.
// Thèmes/Material UI/routing (B25) ne nécessitent aucune configuration Vite
// supplémentaire : React Router utilise `BrowserRouter` côté client (pas de
// plugin de routing basé fichiers), et Vite sert `index.html` en repli pour
// toute route non-`/api` par défaut (`appType: "spa"`, implicite) — un
// rechargement direct sur `/settings` par exemple fonctionne donc déjà.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
});
