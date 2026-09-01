import { useEffect, useRef, useState } from "react";

// §B25 "Client événements temps réel" — décision D058 (voir AVANCEMENT.md) :
// en V1, "temps réel" signifie polling à intervalle court, PAS SSE/WebSocket
// — cette dernière forme est explicitement l'item de checklist de B20
// ("Temps réel via SSE/WebSocket", Alert Dispatcher) et aucun endpoint
// backend de streaming n'existe nulle part dans le projet aujourd'hui.
// Construire un client SSE/WebSocket maintenant, sans aucun vrai endpoint
// pour le faire fonctionner, aurait été exactement le genre de fabrication
// que ce projet évite depuis D033/D047/D051/D057 — un client "prêt" mais
// jamais prouvé contre quoi que ce soit de réel.
//
// Ce hook généralise le pattern déjà utilisé deux fois indépendamment
// (`IncidentBanner.tsx`, B23 : `setInterval` + `fetch` maison ; et la
// boucle de santé de `App.tsx`, B22) en UNE seule primitive réutilisable,
// pour que toute future page (System Health ici, puis Orders/Portfolio/
// Alerts plus tard) n'ait pas à réinventer sa propre boucle de poll. Son
// interface (un état `data`/`error`/`refresh()`) est volontairement
// agnostique du transport sous-jacent : le jour où B20 fait exister un vrai
// flux SSE/WebSocket, cette interface peut être conservée par les pages qui
// l'utilisent déjà, seul `useLivePolling` changerait d'implémentation.
//
// `IncidentBanner.tsx` (B23, déjà livré/tagué v0.17.0) N'EST PAS migré sur
// ce hook — sa boucle de poll est étroitement couplée à sa propre logique de
// transition pulse/bordure (`wasIncidentRef`, timers de pulse/récupération)
// et fonctionne déjà, testée ; la toucher sans raison violerait la
// discipline déjà posée en B23 ("ne pas modifier rétroactivement du code
// livré sans nécessité réelle").

export type LivePollingState<T> = {
  data: T | null;
  error: unknown;
  loading: boolean;
  refresh: () => void;
};

export function useLivePolling<T>(fetcher: () => Promise<T>, intervalMs: number): LivePollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  // Compteur incrémenté pour forcer un cycle de fetch immédiat (bouton
  // "rafraîchir") sans dupliquer la logique de poll ci-dessous.
  const [tick, setTick] = useState(0);
  // Identité stable du fetcher fourni par l'appelant à travers les
  // ré-exécutions de l'effet — évite d'exiger que chaque appelant
  // mémorise sa fonction avec `useCallback` pour ne pas relancer le poll
  // à chaque rendu.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const result = await fetcherRef.current();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    run();
    const id = setInterval(run, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs, tick]);

  return { data, error, loading, refresh: () => setTick((t) => t + 1) };
}
