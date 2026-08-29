"""Bus d'événements Redis Streams — brique B04.

Fournit :
- `publish_event` : XADD d'une `EventEnvelope` sur un stream.
- `EventConsumer` : lecture via consumer group, XACK après traitement durable,
  retry borné avec XCLAIM des messages en attente (PEL), puis routage vers le
  stream dead-letter associé après un nombre maximal d'échecs.

Volontairement simple pour un socle de hackathon : pas de sérialisation
avancée, pas de partitionnement — cohérent avec l'échelle V1 (voir aussi la
roadmap V2 privée pour l'évolution vers des workers horizontaux, non exposée
publiquement).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import redis

from .events import EventEnvelope, Streams

logger = logging.getLogger("eventbus")

DEFAULT_MAX_RETRIES = 5
DEFAULT_BLOCK_MS = 5000
DEFAULT_CLAIM_IDLE_MS = 30_000
# Rétention bornée (B04) : nombre approximatif d'entrées conservées par
# stream. "Approximatif" (`approximate=True`) car un MAXLEN exact force Redis
# à parcourir le stream à chaque XADD — le trim approximatif ne coûte quasi
# rien et suffit largement pour un socle de hackathon (pas de contrainte de
# rétention légale/métier précise en V1). À revoir si un volume réel mesuré
# (B33) montre qu'il faut une valeur différente par stream.
DEFAULT_STREAM_MAXLEN = 10_000


def publish_event(
    client: redis.Redis,
    stream: str,
    envelope: EventEnvelope,
    *,
    maxlen: int = DEFAULT_STREAM_MAXLEN,
) -> str:
    """Publie une enveloppe sur un stream. Retourne l'ID Redis du message.

    `maxlen` borne la rétention (trim approximatif, cf. `DEFAULT_STREAM_MAXLEN`
    ci-dessus) — passer `maxlen=None` pour désactiver le trim sur cet appel
    (ex. tests qui veulent un historique exact).
    """
    payload = envelope.model_dump(mode="json")
    if maxlen is None:
        return client.xadd(stream, {"envelope": json.dumps(payload)})
    return client.xadd(
        stream, {"envelope": json.dumps(payload)}, maxlen=maxlen, approximate=True
    )


def _decode(fields: dict[bytes, bytes]) -> EventEnvelope:
    raw = fields.get(b"envelope") or fields.get("envelope")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return EventEnvelope.model_validate_json(raw)


@dataclass
class ConsumedMessage:
    message_id: str
    envelope: EventEnvelope
    delivery_count: int


class EventConsumer:
    """Consumer group avec retry borné, XACK et routage dead-letter.

    Usage :
        consumer = EventConsumer(client, stream=Streams.STRATEGY_PROPOSAL_CREATED,
                                  group="risk-critic-agent", consumer_name="risk-critic-1")
        consumer.ensure_group()
        for msg in consumer.read():
            try:
                handle(msg.envelope)
                consumer.ack(msg.message_id)
            except Exception:
                consumer.fail(msg.message_id, msg.delivery_count)
    """

    def __init__(
        self,
        client: redis.Redis,
        *,
        stream: str,
        group: str,
        consumer_name: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.client = client
        self.stream = stream
        self.group = group
        self.consumer_name = consumer_name
        self.max_retries = max_retries
        self.dead_letter_stream = Streams.dead_letter(stream)

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def read(self, count: int = 10, block_ms: int = DEFAULT_BLOCK_MS) -> Iterable[ConsumedMessage]:
        response = self.client.xreadgroup(
            self.group, self.consumer_name, {self.stream: ">"}, count=count, block=block_ms
        )
        for _stream_name, messages in response or []:
            for message_id, fields in messages:
                mid = message_id.decode() if isinstance(message_id, bytes) else message_id
                delivery_count = self._delivery_count(mid)
                yield ConsumedMessage(
                    message_id=mid, envelope=_decode(fields), delivery_count=delivery_count
                )

    def reclaim_stale(self, idle_ms: int = DEFAULT_CLAIM_IDLE_MS) -> Iterable[ConsumedMessage]:
        """Reprend les messages restés non-acquittés (PEL) au-delà de `idle_ms` —
        couvre le cas d'un consumer mort en cours de traitement."""
        pending = self.client.xpending_range(
            self.stream, self.group, min="-", max="+", count=50, idle=idle_ms
        )
        for entry in pending:
            mid = entry["message_id"]
            mid = mid.decode() if isinstance(mid, bytes) else mid
            claimed = self.client.xclaim(self.stream, self.group, self.consumer_name, idle_ms, [mid])
            for cid, fields in claimed:
                cid = cid.decode() if isinstance(cid, bytes) else cid
                yield ConsumedMessage(
                    message_id=cid, envelope=_decode(fields), delivery_count=entry["times_delivered"]
                )

    def ack(self, message_id: str) -> None:
        self.client.xack(self.stream, self.group, message_id)

    def fail(self, message_id: str, delivery_count: int) -> None:
        """À appeler quand le traitement échoue. Au-delà de `max_retries`, le
        message est routé vers le stream dead-letter puis acquitté (retiré du
        PEL) sur le stream d'origine."""
        if delivery_count >= self.max_retries:
            fields = self.client.xrange(self.stream, min=message_id, max=message_id)
            if fields:
                _, raw = fields[0]
                self.client.xadd(self.dead_letter_stream, raw)
                logger.warning(
                    "event routed to dead-letter",
                    extra={"correlation_id": message_id, "execution_context_id": None},
                )
            self.ack(message_id)
        # sinon : on laisse le message dans le PEL, il sera repris par reclaim_stale()

    def _delivery_count(self, message_id: str) -> int:
        pending = self.client.xpending_range(
            self.stream, self.group, min=message_id, max=message_id, count=1
        )
        if pending:
            return pending[0]["times_delivered"]
        return 1


def heartbeat_key(service: str) -> str:
    return f"heartbeat:{service}"


# §B22 — états de heartbeat autorisés. STARTING/DISCONNECTED ne sont
# JAMAIS écrits ici : ce sont des déductions faites par le lecteur (watchdog,
# `common/healthcheck.py`) en l'ABSENCE de heartbeat (jamais vu -> STARTING,
# vu puis expiré -> DISCONNECTED), jamais une valeur publiée par le service
# lui-même. HEALTHY/DEGRADED sont publiés à chaque tick de `run_service()`
# selon que `tick()` a réussi ou levé (readiness métier, pas seulement
# "le process boucle"). STOPPED est publié une seule fois, explicitement,
# juste avant un arrêt propre (SIGTERM) — distingue un arrêt volontaire
# (`docker compose down`, déploiement) d'une vraie déconnexion/panne.
HEARTBEAT_PUBLISHED_STATES = ("HEALTHY", "DEGRADED", "STOPPED")


def publish_heartbeat(
    client: redis.Redis, service: str, *, state: str = "HEALTHY", ttl_seconds: int = 15
) -> None:
    """Publie un heartbeat avec TTL (B22) — la clé expire si le service meurt
    (silence radio = DISCONNECTED aux yeux du watchdog, jamais un état publié
    explicitement). Stocké en JSON (`state` + `at`) depuis B22 — avant B22, ce
    n'était qu'un marqueur de vie ("HEALTHY" littéral) sans notion d'état ni
    d'horodatage explicite."""
    if state not in HEARTBEAT_PUBLISHED_STATES:
        raise ValueError(f"état de heartbeat inconnu : {state!r} (attendu {HEARTBEAT_PUBLISHED_STATES})")
    payload = json.dumps({"state": state, "at": datetime.now(UTC).isoformat()})
    client.set(heartbeat_key(service), payload, ex=ttl_seconds)


def read_heartbeat(client: redis.Redis, service: str) -> dict[str, str] | None:
    """Retourne `{"state": ..., "at": ...}` si un heartbeat frais existe (clé
    présente, non expirée), sinon `None` — le lecteur (watchdog) décide seul
    de la déduction STARTING (jamais vu) vs DISCONNECTED (vu puis silence),
    cette fonction ne le sait pas elle-même (elle n'a que l'instant présent,
    pas l'historique)."""
    raw = client.get(heartbeat_key(service))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        parsed = json.loads(raw)
    except ValueError:
        # Compat rétro : une clé encore écrite par l'ancien format (chaîne
        # littérale "HEALTHY", avant B22) reste lisible plutôt que de casser
        # un déploiement en cours de rolling-update image par image.
        return {"state": raw, "at": ""} if raw in HEARTBEAT_PUBLISHED_STATES else None
    if not isinstance(parsed, dict) or "state" not in parsed:
        return None
    return parsed
