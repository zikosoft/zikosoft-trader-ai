"""Cœur des contextes d'exécution Replay/Paper (B06).

Le schéma (`execution_contexts`, `ExecutionContextMixin`) existe depuis B03
(§4.2 — PAPER/REPLAY/DRY_RUN, filtrage obligatoire par contexte). B06 ajoute
le comportement autour : sélection ("Choose your experience"), changement
atomique avec confirmation, suspension des stratégies du contexte quitté,
et le contrat d'événement (`context.switched`) que les futurs workers/agents
(B10+) consommeront pour fermer leurs streams/abonnements côté contexte
quitté — aucun consommateur réel n'existe encore, comme pour B04 en son
temps (le contrat est publié et testé avant d'avoir de vrais abonnés).

Seuls PAPER et REPLAY sont proposés à l'utilisateur (cartes "Choose your
experience", §B06). DRY_RUN existe en base pour un usage interne futur
(tests/QA, B33) mais n'est jamais sélectionnable depuis l'API.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.eventbus import publish_event
from shared.events import EventEnvelope, Streams

from .models import ExecutionContext, ExecutionContextSwitch, Strategy, User

SELECTABLE_KINDS: tuple[str, ...] = ("PAPER", "REPLAY")
ALL_KINDS: tuple[str, ...] = ("PAPER", "REPLAY", "DRY_RUN")

_DEFAULT_LABELS = {
    "PAPER": "Alpaca Paper",
    "REPLAY": "Historical Replay",
    "DRY_RUN": "Dry Run (interne, tests/QA — B33)",
}


class ContextConfirmationRequired(Exception):
    """Levée quand on tente de quitter un contexte déjà actif sans avoir
    posé `confirm=true` (§B06 "Confirmation avant changement de contexte").
    Le premier choix après login (aucun contexte encore actif) ne lève
    jamais cette exception — il n'y a rien à confirmer."""

    def __init__(self, active: ExecutionContext, target: ExecutionContext) -> None:
        self.active = active
        self.target = target
        super().__init__(
            f"confirmation required to switch from {active.kind} to {target.kind}"
        )


def ensure_user_contexts(db: Session, user: User) -> dict[str, ExecutionContext]:
    """Garantit que les 3 emplacements de contexte existent pour `user` et
    les retourne indexés par `kind`. Le seed (`seed.py`) les crée déjà pour
    l'utilisateur démo au démarrage — cette fonction est défensive (idempotente,
    ne recrée jamais un doublon) pour tout autre utilisateur futur (V2)."""
    rows = db.execute(
        select(ExecutionContext).where(ExecutionContext.user_id == user.id)
    ).scalars().all()
    by_kind = {row.kind: row for row in rows}
    for kind in ALL_KINDS:
        if kind not in by_kind:
            row = ExecutionContext(
                kind=kind, label=_DEFAULT_LABELS[kind], user_id=user.id, is_active=False
            )
            db.add(row)
            db.flush()
            by_kind[kind] = row
    return by_kind


def active_context(contexts: dict[str, ExecutionContext]) -> ExecutionContext | None:
    return next((c for c in contexts.values() if c.is_active), None)


def switch_context(
    db: Session,
    redis_client_: redis.Redis,
    user: User,
    target_kind: str,
    *,
    confirm: bool,
) -> tuple[ExecutionContext, dict[str, ExecutionContext]]:
    """Change le contexte actif de `user` vers `target_kind`, de façon
    atomique (une transaction : suspension des stratégies actives du
    contexte quitté, désactivation de l'ancien, activation du nouveau,
    entrée d'audit, événement `context.switched`). Aucune donnée n'est
    supprimée — seul `is_active` change (§B06 "conservation des données de
    chaque contexte").

    Lève `ContextConfirmationRequired` si `target_kind` diffère du contexte
    déjà actif et que `confirm` n'est pas `True` — l'appelant doit alors
    rejouer l'appel avec `confirm=True` après confirmation utilisateur.
    """
    if target_kind not in SELECTABLE_KINDS:
        raise ValueError(f"kind non sélectionnable : {target_kind!r}")

    contexts = ensure_user_contexts(db, user)
    target = contexts[target_kind]
    active = active_context(contexts)

    if active is not None and active.id == target.id:
        return target, contexts  # déjà actif — no-op, pas de log/événement

    if active is not None and not confirm:
        raise ContextConfirmationRequired(active=active, target=target)

    suspended_strategy_ids: list[uuid.UUID] = []
    if active is not None:
        strategies = db.execute(
            select(Strategy).where(
                Strategy.execution_context_id == active.id, Strategy.status == "ACTIVE"
            )
        ).scalars().all()
        for strategy in strategies:
            strategy.status = "PAUSED"
            suspended_strategy_ids.append(strategy.id)
        active.is_active = False
        db.flush()

    target.is_active = True
    db.flush()

    db.add(
        ExecutionContextSwitch(
            user_id=user.id,
            from_context_id=active.id if active else None,
            to_context_id=target.id,
            confirmed=bool(active) and confirm,
        )
    )
    db.flush()

    envelope = EventEnvelope(
        event_type="context.switched",
        correlation_id=uuid.uuid4(),
        user_id=user.id,
        execution_context_id=target.id,
        payload={
            "from_context_id": str(active.id) if active else None,
            "from_kind": active.kind if active else None,
            "to_context_id": str(target.id),
            "to_kind": target.kind,
            "suspended_strategy_ids": [str(i) for i in suspended_strategy_ids],
            "switched_at": datetime.now(UTC).isoformat(),
        },
    )
    # Contrat pour les futurs workers/agents (B10+) : fermer les streams et
    # abonnements liés à `from_context_id` à réception de cet événement.
    # Aucun consommateur réel n'existe encore (voir docstring du module).
    publish_event(redis_client_, Streams.SYSTEM_EVENTS, envelope)

    return target, contexts
