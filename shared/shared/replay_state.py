"""État de session Replay (B19, Étape A) — position courante d'un
`ReplayMarketDataProvider` pour un `execution_context_id` REPLAY donné.

Stocké dans Redis, pas une table PostgreSQL dédiée — même principe que
`shared.risk_governance`/`shared.ai_governance` (B15/B10) : c'est un état de
SIMULATION éphémère et redémarrable à tout moment (« Restart déterministe »,
§checklist B19), pas un enregistrement métier à auditer durablement. Une clé
par contexte d'exécution (jamais partagée entre contextes — §R06 isolation
Replay/Paper, qui s'applique ici même si les deux côtés de l'isolation sont
tous les deux potentiellement REPLAY : deux contextes REPLAY distincts, s'ils
existaient, ne partageraient jamais leur position de lecture)."""

from __future__ import annotations

import json
import uuid

_KEY_PREFIX = "replay:session:"


def _key(execution_context_id: uuid.UUID) -> str:
    return f"{_KEY_PREFIX}{execution_context_id}"


def get_replay_session(redis_client, execution_context_id: uuid.UUID) -> dict | None:
    raw = redis_client.get(_key(execution_context_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        return json.loads(raw)
    except ValueError:
        return None


def set_replay_session(redis_client, execution_context_id: uuid.UUID, *, dataset_id: str, index: int) -> None:
    redis_client.set(_key(execution_context_id), json.dumps({"dataset_id": dataset_id, "index": index}))


def clear_replay_session(redis_client, execution_context_id: uuid.UUID) -> None:
    redis_client.delete(_key(execution_context_id))
