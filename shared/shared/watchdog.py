"""Contrat partagé du Watchdog (B22) — la liste des « services essentiels »
et les états possibles, importés à la fois par `workers/watchdog/main.py`
(qui les écrit) et `backend/app/main.py::system_health()` (qui les lit) pour
qu'ils ne puissent jamais diverger silencieusement (même discipline que
`shared/shared/events.py::Streams` pour les noms de stream)."""

from __future__ import annotations

# §checklist B22 "Services essentiels" — exactement ces 9, ni plus ni moins.
# `portfolio-worker`/`alert-worker`/`watchdog` (lui-même) existent mais ne
# sont volontairement PAS dans cette liste : la checklist B22 ne les nomme
# pas, et les ajouter aurait été une extension de périmètre non demandée.
ESSENTIAL_SERVICES: tuple[str, ...] = (
    "backend-api",
    "postgres",
    "redis",
    "market-agent",
    "strategy-agent",
    "risk-critic-agent",
    "execution-explanation-agent",
    "risk-engine",
    "order-worker",
)

# §checklist B22 "États STARTING/HEALTHY/DEGRADED/DISCONNECTED/STOPPED".
STARTING = "STARTING"
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
DISCONNECTED = "DISCONNECTED"
STOPPED = "STOPPED"

# Services dont le conteneur est vivant et opérationnel du point de vue de
# la démo (pas d'incident affiché) — DEGRADED y figure : un service qui
# boucle mais dont le dernier `tick()` a échoué reste rattrapable au tick
# suivant, ce n'est pas encore une déconnexion.
OPERATIONAL_STATES = (HEALTHY, DEGRADED)
