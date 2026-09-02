// B23 — UX incident critique rouge. Bandeau + bordure persistante affichés
// dès qu'au moins un des 9 services essentiels (B22) est DEGRADED ou
// DISCONNECTED — jamais sur STARTING seul (un démarrage à froid normal,
// ex. `docker compose up`, ne doit pas ressembler à une panne, voir
// AVANCEMENT.md D056) ni sur une déconnexion réseau ponctuelle du
// navigateur lui-même (traité séparément, voir `unreachable` ci-dessous).
//
// Montée systématiquement en tête de l'arbre React (voir App.tsx) — visible
// sur TOUTES les vues, y compris avant connexion (la route est publique,
// voir api/systemHealth.ts), puisqu'un incident système concerne tout le
// monde.

import { useCallback, useEffect, useRef, useState } from "react";
import "./IncidentBanner.css";
import { fetchSystemHealth, SERVICE_LABELS, type ServiceCheck, type SystemHealth } from "./api/systemHealth";
import { formatDateTime } from "./i18n/formatters";
import { useI18n } from "./i18n/I18nContext";
import { serviceLabel } from "./i18n/domain";

// §checklist "Heartbeat toutes les 5 secondes" (B22) — même cadence côté
// lecture, inutile d'interroger plus souvent que la donnée ne peut changer.
const POLL_INTERVAL_MS = 5000;

// §checklist "Pulse rouge trois fois" — doit rester synchronisé avec
// `@keyframes incident-pulse` dans IncidentBanner.css (0.6s * 3).
const PULSE_DURATION_MS = 1800;

// §checklist "Message de récupération" — confirmation transitoire affichée
// après un retour à la normale, avant de disparaître d'elle-même. Une
// disparition silencieuse du bandeau rouge aurait laissé Zac/un jury dans
// le doute (« l'incident est-il vraiment terminé, ou le bandeau a-t-il
// juste buggé ? ») — ce message ferme explicitement la boucle.
const RECOVERY_MESSAGE_DURATION_MS = 6000;

// §B25 : `SERVICE_LABELS` déménagé vers `api/systemHealth.ts` (source
// unique, partagée avec la nouvelle page System Health) — importé ci-dessus.

// §checklist "Impact fonctionnel" — description honnête et spécifique par
// service plutôt qu'un message générique ("un problème est survenu") qui
// n'aiderait ni Zac ni un jury à comprendre ce qui est réellement affecté.
const SERVICE_IMPACT_KEYS: Record<string, string> = {
  "backend-api": "incident.impact.backendApi",
  postgres: "incident.impact.postgres",
  redis: "incident.impact.redis",
  "market-agent": "incident.impact.marketAgent",
  "strategy-agent": "incident.impact.strategyAgent",
  "risk-critic-agent": "incident.impact.riskCriticAgent",
  "execution-explanation-agent": "incident.impact.executionExplanationAgent",
  "risk-engine": "incident.impact.riskEngine",
  "order-worker": "incident.impact.orderWorker",
};

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function isAffected(check: ServiceCheck): boolean {
  return check.status === "DEGRADED" || check.status === "DISCONNECTED";
}

export default function IncidentBanner() {
  const { locale, t } = useI18n();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [pulsing, setPulsing] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [recovered, setRecovered] = useState(false);
  const wasIncidentRef = useRef(false);
  const pulseTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recoveryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(async () => {
    try {
      const result = await fetchSystemHealth();
      setHealth(result);
      setUnreachable(false);
    } catch {
      // §"backend-api" lui-même injoignable (pas seulement DEGRADED) — le
      // pire cas, honnêtement distinct d'une réponse HTTP qui dit DEGRADED.
      setUnreachable(true);
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [poll]);

  const affected = health ? Object.entries(health.checks).filter(([, c]) => isAffected(c)) : [];
  const hasIncident = unreachable || affected.length > 0;

  useEffect(() => {
    if (hasIncident && !wasIncidentRef.current) {
      // Transition saine -> incident : déclenche le pulse (sauf préférence
      // utilisateur pour un mouvement réduit, où l'on passe directement à
      // l'état "bordure persistante" sans laisser de fenêtre sans bordure).
      if (prefersReducedMotion()) {
        setPulsing(false);
      } else {
        setPulsing(true);
        pulseTimeoutRef.current = setTimeout(() => setPulsing(false), PULSE_DURATION_MS);
      }
    }
    if (!hasIncident) {
      setPulsing(false);
      setDetailsOpen(false);
      if (pulseTimeoutRef.current) {
        clearTimeout(pulseTimeoutRef.current);
        pulseTimeoutRef.current = null;
      }
      // Transition incident -> sain : affiche une confirmation transitoire
      // (jamais au montage initial si aucun incident n'a jamais eu lieu —
      // `wasIncidentRef.current` n'est vrai que si un vrai incident a
      // précédé cette transition).
      if (wasIncidentRef.current) {
        setRecovered(true);
        recoveryTimeoutRef.current = setTimeout(() => setRecovered(false), RECOVERY_MESSAGE_DURATION_MS);
      }
    } else if (recoveryTimeoutRef.current) {
      // Un nouvel incident démarre pendant que le message de récupération
      // précédent était encore affiché : ne pas le laisser survivre au
      // nouvel incident.
      clearTimeout(recoveryTimeoutRef.current);
      recoveryTimeoutRef.current = null;
      setRecovered(false);
    }
    wasIncidentRef.current = hasIncident;
  }, [hasIncident]);

  useEffect(() => {
    return () => {
      if (pulseTimeoutRef.current) clearTimeout(pulseTimeoutRef.current);
      if (recoveryTimeoutRef.current) clearTimeout(recoveryTimeoutRef.current);
    };
  }, []);

  const borderClass = hasIncident
    ? `incident-border ${pulsing ? "incident-border--pulsing" : "incident-border--active"}`
    : "incident-border";

  return (
    <>
      <div className={borderClass} aria-hidden="true" />
      {!hasIncident && recovered && (
        // §checklist "Message de récupération" — confirmation transitoire,
        // se ferme seule (RECOVERY_MESSAGE_DURATION_MS) ; un bouton de
        // fermeture manuelle est acceptable ici (contrairement au bandeau
        // d'incident actif) puisqu'aucune panne n'est plus en cours.
        <div className="recovery-banner" role="status">
          <span>{t("incident.recovered")}</span>
          <button
            className="recovery-banner__button"
            onClick={() => {
              if (recoveryTimeoutRef.current) {
                clearTimeout(recoveryTimeoutRef.current);
                recoveryTimeoutRef.current = null;
              }
              setRecovered(false);
            }}
            type="button"
          >
            ×
          </button>
        </div>
      )}
      {hasIncident && (
        // §checklist "Bandeau non fermable tant que panne active" — aucun
        // bouton de fermeture nulle part dans ce composant, intentionnellement.
        <div className="incident-banner" role="alert">
          <div className="incident-banner__header">
            <span className="incident-banner__title">
              {unreachable
                ? t("incident.backendUnreachable")
                : t(affected.length === 1 ? "incident.active.one" : "incident.active.other", { count: affected.length })}
            </span>
            <span className="incident-banner__actions">
              <button className="incident-banner__button" onClick={poll} type="button">
                {t("incident.retryDiagnostics")}
              </button>
              {!unreachable && (
                <button
                  className="incident-banner__button"
                  onClick={() => setDetailsOpen((v) => !v)}
                  type="button"
                >
                  {detailsOpen ? t("incident.hideTechnicalDetails") : t("incident.showTechnicalDetails")}
                </button>
              )}
            </span>
          </div>
          {!unreachable && (
            <ul className="incident-banner__service-list">
              {affected.map(([name, check]) => (
                <li key={name} className="incident-banner__service">
                  <strong>{serviceLabel(t, name, SERVICE_LABELS[name] ?? name)}</strong> —{" "}
                  {t(`status.${check.status}`)}
                  {check.last_heartbeat_at
                    ? t("incident.lastSignal", {
                        time: formatDateTime(locale, check.last_heartbeat_at, { timeStyle: "short" }),
                      })
                    : t("incident.noSignal")}
                  . {t(SERVICE_IMPACT_KEYS[name] ?? "incident.impact.unknown")}
                </li>
              ))}
            </ul>
          )}
          {detailsOpen && health && (
            <pre className="incident-banner__details">{JSON.stringify(health.checks, null, 2)}</pre>
          )}
        </div>
      )}
    </>
  );
}
