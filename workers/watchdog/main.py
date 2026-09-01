"""watchdog — B22, agrège la santé des 9 « services essentiels »
(`shared.watchdog.ESSENTIAL_SERVICES`) et persiste chaque CHANGEMENT d'état
dans `service_health_events` (table posée dès B03) + publie un événement
`system.events` par transition, jamais un événement à chaque tick (§checklist
"Dédoublonnage") — seule une transition réelle (par rapport au dernier état
connu, lu en base plutôt qu'en mémoire, même discipline que `portfolio_worker`
D045 : survit à un redémarrage du watchdog lui-même) déclenche une écriture
et une publication.

Comme `market_agent`/`risk_engine`/`portfolio_worker` (B10/B15/B18), ce
module n'a pas accès aux modèles ORM de `backend` (image Docker séparée,
§B01) — tout passe par du SQL brut via `text()`.

**`postgres`/`redis`** sont vérifiés en direct ici (connexion réelle) — ce
sont des dépendances externes sans mécanisme de heartbeat applicatif propre.
**Les 7 autres** (`backend-api` + les 6 agents/workers du pipeline métier)
sont lus via leur heartbeat Redis (`shared.eventbus.read_heartbeat`,
publié par `common.bootstrap.run_service`/`backend/app/main.py` — B22) :
`STARTING` si jamais observé, `DISCONNECTED` si observé par le passé
(une ligne existe déjà dans `service_health_events`) puis silence radio
(heartbeat expiré), sinon l'état publié tel quel (`HEALTHY`/`DEGRADED`/
`STOPPED`).

**`execution_context_id=None`** sur les événements publiés ici (voir
`shared/shared/events.py`, assoupli le 26/08 pour ce cas précis) : l'état
d'un service backend n'appartient à aucun contexte Paper/Replay."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import redis
from common.bootstrap import run_service
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shared.eventbus import publish_event, read_heartbeat
from shared.events import EventEnvelope, Streams
from shared.watchdog import (
    DEGRADED,
    DISCONNECTED,
    ESSENTIAL_SERVICES,
    HEALTHY,
    STARTING,
    STOPPED,
)

logger = logging.getLogger("watchdog")

_HEARTBEAT_TRACKED_STATES = (HEALTHY, DEGRADED, STOPPED)

_LATEST_STATES_SQL = text(
    """
    SELECT DISTINCT ON (service_name) service_name, state
    FROM service_health_events
    WHERE service_name = ANY(:service_names)
    ORDER BY service_name, created_at DESC
    """
)

_INSERT_HEALTH_EVENT_SQL = text(
    """
    INSERT INTO service_health_events (id, service_name, state, detail, last_heartbeat_at)
    VALUES (:id, :service_name, :state, CAST(:detail AS jsonb), :last_heartbeat_at)
    """
)


def _observe_postgres(engine: Engine) -> tuple[str, datetime | None]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return HEALTHY, datetime.now(UTC)
    except Exception:  # noqa: BLE001 — toute erreur de connexion = service injoignable
        return DISCONNECTED, None


def _observe_redis(redis_client: redis.Redis) -> tuple[str, datetime | None]:
    try:
        redis_client.ping()
        return HEALTHY, datetime.now(UTC)
    except Exception:  # noqa: BLE001
        return DISCONNECTED, None


def _observe_heartbeat_service(
    redis_client: redis.Redis, service_name: str, *, previously_seen: bool
) -> tuple[str, datetime | None]:
    hb = read_heartbeat(redis_client, service_name)
    if hb is None:
        # Jamais observé -> encore en train de démarrer ; déjà observé par le
        # passé (une ligne existe en base) puis silence -> vraie déconnexion.
        return (DISCONNECTED if previously_seen else STARTING), None

    state = hb.get("state")
    if state not in _HEARTBEAT_TRACKED_STATES:
        # Valeur inattendue (bug amont, format futur non prévu) : ne jamais
        # planter dessus ni la fabriquer comme HEALTHY par défaut — DEGRADED
        # signale honnêtement "quelque chose ne va pas" sans sur-interpréter.
        state = DEGRADED

    at_raw = hb.get("at") or None
    last_heartbeat_at: datetime | None = None
    if at_raw:
        try:
            last_heartbeat_at = datetime.fromisoformat(at_raw)
        except ValueError:
            last_heartbeat_at = None
    return state, last_heartbeat_at


def _record_transition(
    engine: Engine,
    redis_client: redis.Redis,
    *,
    service_name: str,
    previous_state: str | None,
    new_state: str,
    last_heartbeat_at: datetime | None,
) -> None:
    detail: dict[str, Any] = {"previous_state": previous_state, "new_state": new_state}
    with engine.begin() as conn:
        conn.execute(
            _INSERT_HEALTH_EVENT_SQL,
            {
                "id": uuid.uuid4(),
                "service_name": service_name,
                "state": new_state,
                "detail": json.dumps(detail),
                "last_heartbeat_at": last_heartbeat_at,
            },
        )

    # §checklist "Événement incident" / "Détection récupération" : un seul
    # type d'événement, les deux notions dérivées honnêtement des deux états
    # comparés plutôt que deux schémas distincts pour la même transition
    # (voir AVANCEMENT.md, décision B22 sur ce choix de conception).
    is_incident = new_state in (DEGRADED, DISCONNECTED)
    is_recovery = previous_state in (DEGRADED, DISCONNECTED) and new_state == HEALTHY
    envelope = EventEnvelope(
        event_type="system.service.health_changed",
        correlation_id=uuid.uuid4(),
        execution_context_id=None,
        payload={
            "service_name": service_name,
            "previous_state": previous_state,
            "new_state": new_state,
            "is_incident": is_incident,
            "is_recovery": is_recovery,
            "last_heartbeat_at": last_heartbeat_at.isoformat() if last_heartbeat_at else None,
        },
    )
    publish_event(redis_client, Streams.SYSTEM_EVENTS, envelope)
    logger.info(
        "watchdog: %s %s -> %s%s",
        service_name,
        previous_state,
        new_state,
        " (incident)" if is_incident else " (récupération)" if is_recovery else "",
    )


def tick(engine: Engine, redis_client: redis.Redis) -> None:
    with engine.connect() as conn:
        rows = conn.execute(_LATEST_STATES_SQL, {"service_names": list(ESSENTIAL_SERVICES)}).mappings().all()
    latest_known_state = {row["service_name"]: row["state"] for row in rows}

    for service_name in ESSENTIAL_SERVICES:
        prior_state = latest_known_state.get(service_name)
        if service_name == "postgres":
            new_state, observed_at = _observe_postgres(engine)
        elif service_name == "redis":
            new_state, observed_at = _observe_redis(redis_client)
        else:
            # "Déjà vu en HEALTHY/DEGRADED/STOPPED/DISCONNECTED au moins une
            # fois" — pas "une ligne existe" tout court : `STARTING` lui-même
            # est enregistré en base (pour le dédoublonnage, voir plus bas),
            # donc `prior_state == STARTING` ne doit JAMAIS faire basculer
            # l'observation suivante vers `DISCONNECTED` (un service qui n'a
            # simplement jamais démarré n'est pas "déconnecté").
            previously_seen = prior_state not in (None, STARTING)
            new_state, observed_at = _observe_heartbeat_service(
                redis_client, service_name, previously_seen=previously_seen
            )

        if new_state == prior_state:
            continue  # §checklist "Dédoublonnage" — aucun changement, rien à écrire ni publier

        try:
            _record_transition(
                engine,
                redis_client,
                service_name=service_name,
                previous_state=prior_state,
                new_state=new_state,
                last_heartbeat_at=observed_at,
            )
        except Exception:  # noqa: BLE001 — un échec sur un service ne doit pas bloquer les suivants
            logger.exception("watchdog: échec d'enregistrement de transition pour %s", service_name)


if __name__ == "__main__":
    run_service("watchdog", tick)
