"""alert-worker — B20, Alert Dispatcher. Premier vrai consommateur du
stream `system.events` côté notifications (le Watchdog, B22, le publie
depuis le premier jour — `system.service.health_changed` — mais jusqu'ici
personne ne le lisait). Traduit chaque transition de santé de service en
ligne(s) `Alert` (§B03, jamais alimentée jusqu'ici) — une par contexte
d'exécution existant, voir `_process_health_changed` ci-dessous.

Comme `market_agent`/`risk_engine`/`portfolio_worker` (B10/B15/B18), ce
module n'a pas accès aux modèles ORM de `backend` (image Docker séparée,
§B01) — tout passe par du SQL brut via `text()`.

**Portée V1 honnête : seul `system.service.health_changed` est traité.**
`Streams.ALERT_EVENTS` ("alert.events", défini depuis B04, jamais utilisé
jusqu'ici) devient le canal de PUBLICATION de ce worker (une ligne
`alert.created` par `Alert` écrite) — pour un futur consommateur (B21
Telegram, ou un futur transport temps réel qui remplacerait le polling
D058) — mais aucun événement METIER (proposition de stratégie, ordre,
décision de risque...) n'est encore mappé vers une alerte : ce mapping
appartiendrait à chaque agent/worker producteur (ex. Order Worker pour un
ordre rejeté), pas à ce Dispatcher générique, et n'a été demandé par
aucune checklist B20 explicite au-delà du Watchdog et du kill switch
(celui-ci écrit directement via l'ORM, voir `backend/app/kill_switch.py`
— seul appelant qui a un existant accès `Session`).

**Déduplication (§checklist "Déduplication") :** `dedup_key` combine
l'`event_id` de l'enveloppe Watchdog et l'`execution_context_id` visé —
un même événement redistribué (redélivrance Redis Streams après crash
avant `ack`, `reclaim_stale`) ne crée jamais une deuxième ligne pour le
même contexte. Pré-vérification non atomique (même limite assumée que
`_already_explained`/`_already_critiqued` ailleurs dans le projet) : une
vraie contrainte unique sur `alerts.dedup_key` n'existe pas (colonne
simplement indexée, §B03) — un doublon extrêmement rare sous concurrence
réelle resterait possible, mais un unique alert_worker tourne en pratique
(un seul réplica, `docker-compose.yml`), donc pas de concurrence réelle
sur cette pré-vérification aujourd'hui."""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid

import redis
from common.bootstrap import run_service
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shared.eventbus import EventConsumer, publish_event
from shared.events import EventEnvelope, Streams

logger = logging.getLogger("alert-worker")

GROUP_NAME = "alert-worker"
CONSUMER_NAME = f"alert-worker-{socket.gethostname()}-{os.getpid()}"

READ_COUNT = 10
READ_BLOCK_MS = 2000
RECLAIM_IDLE_MS = 30_000

_SEVERITY_CRITICAL = "CRITICAL"
_SEVERITY_WARNING = "WARNING"
_SEVERITY_INFO = "INFO"

_ALL_CONTEXTS_SQL = text("SELECT id, user_id FROM execution_contexts")

_DEDUP_CHECK_SQL = text("SELECT 1 FROM alerts WHERE dedup_key = :dedup_key LIMIT 1")

_ALERT_INSERT_SQL = text(
    """
    INSERT INTO alerts
        (id, user_id, execution_context_id, category, severity, title, message,
         related_entity_type, related_entity_id, is_read, dedup_key, metadata_json)
    VALUES
        (:id, :user_id, :execution_context_id, :category, :severity, :title, :message,
         'service', NULL, false, :dedup_key, CAST(:metadata_json AS jsonb))
    """
)


def _severity_for(*, new_state: str, is_recovery: bool) -> str:
    if is_recovery:
        return _SEVERITY_INFO
    if new_state == "DISCONNECTED":
        return _SEVERITY_CRITICAL
    if new_state == "DEGRADED":
        return _SEVERITY_WARNING
    return _SEVERITY_INFO


def _title_and_message(*, service_name: str, new_state: str, is_incident: bool, is_recovery: bool) -> tuple[str, str]:
    if is_recovery:
        return (
            f"{service_name} rétabli",
            f"Le service « {service_name} » est de nouveau HEALTHY après une interruption.",
        )
    if is_incident:
        return (
            f"{service_name} — {new_state}",
            f"Le service « {service_name} » est passé à l'état {new_state}. Voir System Health pour le détail.",
        )
    return (f"{service_name} — {new_state}", f"Le service « {service_name} » est passé à l'état {new_state}.")


def _process_health_changed(engine: Engine, redis_client: redis.Redis, envelope: EventEnvelope) -> None:
    payload = envelope.payload or {}
    service_name = payload.get("service_name")
    new_state = payload.get("new_state")
    is_incident = bool(payload.get("is_incident"))
    is_recovery = bool(payload.get("is_recovery"))
    if not service_name or not new_state:
        logger.error("événement system.service.health_changed mal formé, ignoré")
        return

    # §checklist "Alerte uniquement sur incident/récupération" — un
    # changement d'état qui n'est ni l'un ni l'autre (ex. STARTING ->
    # HEALTHY au tout premier démarrage, jamais un incident) ne produit
    # délibérément aucune alerte : bruiter le centre de notifications dès
    # le boot de chaque service serait contre-productif.
    if not is_incident and not is_recovery:
        return

    severity = _severity_for(new_state=new_state, is_recovery=is_recovery)
    title, message = _title_and_message(
        service_name=service_name, new_state=new_state, is_incident=is_incident, is_recovery=is_recovery
    )
    metadata = {
        "service_name": service_name,
        "new_state": new_state,
        "previous_state": payload.get("previous_state"),
        "is_incident": is_incident,
        "is_recovery": is_recovery,
    }

    with engine.connect() as conn:
        contexts = conn.execute(_ALL_CONTEXTS_SQL).mappings().all()

    for ctx in contexts:
        dedup_key = f"health:{envelope.event_id}:{ctx['id']}"
        with engine.connect() as conn:
            already = conn.execute(_DEDUP_CHECK_SQL, {"dedup_key": dedup_key}).first()
        if already is not None:
            continue

        alert_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                _ALERT_INSERT_SQL,
                {
                    "id": alert_id,
                    "user_id": ctx["user_id"],
                    "execution_context_id": ctx["id"],
                    "category": "system_health",
                    "severity": severity,
                    "title": title,
                    "message": message,
                    "dedup_key": dedup_key,
                    "metadata_json": json.dumps(metadata),
                },
            )

        # §Streams.ALERT_EVENTS — voir docstring du module : aucun
        # consommateur aujourd'hui, publié pour B21/un futur transport
        # temps réel sans avoir à retoucher ce Dispatcher plus tard.
        publish_event(
            redis_client,
            Streams.ALERT_EVENTS,
            EventEnvelope(
                event_type="alert.created",
                correlation_id=envelope.correlation_id,
                causation_id=envelope.event_id,
                user_id=ctx["user_id"],
                execution_context_id=ctx["id"],
                payload={
                    "alert_id": str(alert_id),
                    "category": "system_health",
                    "severity": severity,
                    "title": title,
                    "message": message,
                },
            ),
        )

    logger.info(
        "alerte(s) dispatchée(s) pour %s -> %s (%d contexte(s))",
        service_name,
        new_state,
        len(contexts),
    )


def _process_envelope(engine: Engine, redis_client: redis.Redis, envelope: EventEnvelope) -> None:
    if envelope.event_type != "system.service.health_changed":
        return
    _process_health_changed(engine, redis_client, envelope)


def tick(engine: Engine, redis_client: redis.Redis) -> None:
    consumer = EventConsumer(
        redis_client,
        stream=Streams.SYSTEM_EVENTS,
        group=GROUP_NAME,
        consumer_name=CONSUMER_NAME,
    )
    consumer.ensure_group()

    for message in consumer.read(count=READ_COUNT, block_ms=READ_BLOCK_MS):
        try:
            _process_envelope(engine, redis_client, message.envelope)
            consumer.ack(message.message_id)
        except Exception:  # noqa: BLE001 — un message en échec ne doit jamais arrêter le tick (§B04 retry/dead-letter)
            logger.exception("échec du traitement d'un événement système")
            consumer.fail(message.message_id, message.delivery_count)

    for message in consumer.reclaim_stale(idle_ms=RECLAIM_IDLE_MS):
        try:
            _process_envelope(engine, redis_client, message.envelope)
            consumer.ack(message.message_id)
        except Exception:  # noqa: BLE001 — voir commentaire ci-dessus
            logger.exception("échec du traitement d'un événement système repris (PEL)")
            consumer.fail(message.message_id, message.delivery_count)


if __name__ == "__main__":
    run_service("alert-worker", tick)
