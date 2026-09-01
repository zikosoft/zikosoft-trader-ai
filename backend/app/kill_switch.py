"""B31 — Kill switch trading (§checklist : bouton global, confirmation
renforcée, suspension des stratégies, blocage des nouvelles propositions
exécutables, blocage de l'Order Worker, annulation des ordres ouverts
éligibles, audit event, alertes in-app/Telegram, récupération explicite
jamais automatique, tests concurrence/idempotence).

**Aucune migration Alembic pour cette brique** — contrairement à la
plupart des bricks précédentes : le flag lui-même vit déjà dans Redis
(`shared.risk_governance`, posé en B15/D031) et la trace d'audit réutilise
`AuditEvent` (`backend/app/models/ops.py`), une table posée dès le socle
B03 dont le docstring cite déjà explicitement "kill switch" parmi ses cas
d'usage prévus — exactement le même principe que D069 (étendre une pièce
d'infrastructure déjà posée mais encore inutilisée plutôt que d'en créer
une nouvelle en double).

**Source de vérité et ordre des écritures (concurrence/idempotence,
§checklist) :** un verrou transactionnel Postgres (`pg_advisory_xact_lock`,
libéré automatiquement à la fin de la transaction FastAPI/`get_db`) sérialise
tout engage/disengage concurrent — deux requêtes simultanées ne peuvent
jamais toutes les deux exécuter les effets de bord (suspension des
stratégies, ligne d'audit). À l'intérieur du verrou, l'état actuel est relu
depuis Redis ; si l'action demandée est déjà l'état courant, la fonction est
un NO-OP idempotent (aucune ligne d'audit dupliquée, aucune stratégie
re-suspendue). Le flag Redis n'est écrit qu'APRÈS que les écritures
PostgreSQL (suspension des stratégies + ligne d'audit) ont été préparées
dans la même transaction — si `set_trading_kill_switch_engaged` lève une
exception, `get_db()` annule (`rollback`) tout le reste, aucun état
partiellement appliqué ne survit. C'est un choix délibéré : en cas d'échec
à mi-chemin, l'état RESTE celui d'avant l'appel (jamais un état bâtard) —
le pire résultat possible est un engage/disengage qui échoue proprement et
que l'opérateur peut retenter, jamais un flag Redis à `true` sans les
stratégies réellement suspendues ni de ligne d'audit qui l'explique.

**Récupération explicite, jamais automatique (§checklist) :** `disengage()`
ne réactive JAMAIS les stratégies suspendues par `engage()` — elles
restent `PAUSED`, à réactiver une par une via le cycle de vie B12 existant.
Une réactivation automatique aurait remis le trading en marche sans
qu'aucune décision explicite par stratégie n'ait été reprise, contraire à
l'esprit même de "jamais automatique" appliqué au trading, pas seulement à
l'interrupteur lui-même.

**Annulation des ordres ouverts éligibles :** cette fonction NE parle PAS
directement à Alpaca (respecte D006/D037 — "Order Worker seul autorisé à
exécuter" — l'annulation est aussi une écriture Alpaca à effet de bord,
même discipline que la soumission). `workers/order_worker/main.py` détecte
le flag à chaque `tick()` et effectue le balayage réel des ordres ouverts
(`NON_TERMINAL_STATUSES`, déjà défini en B17 pour la réconciliation REST)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from shared.risk_governance import get_trading_kill_switch_engaged, set_trading_kill_switch_engaged

from .context import ensure_user_contexts
from .models import Alert, AuditEvent, Strategy, User
from .strategy_instances import STATUS_ACTIVE, STATUS_PAUSED

# §B20 — contextes concernés par une alerte kill switch : Paper (trading
# réel simulé) et Replay (l'utilisateur y observe des stratégies qui
# viennent d'être suspendues) ; DRY_RUN volontairement exclu, aucune
# stratégie n'y tourne jamais (§B12, portée V1).
_ALERTABLE_CONTEXT_KINDS = ("PAPER", "REPLAY")

# Clé arbitraire fixe pour `pg_advisory_xact_lock` — un seul verrou pour
# tout le processus kill switch (portée globale, pas par contexte, cohérent
# avec le flag Redis lui-même qui n'a jamais été scopé par contexte, voir
# `risk_governance.py`).
_ADVISORY_LOCK_KEY = 875_331_209

ACTION_ENGAGED = "KILL_SWITCH_ENGAGED"
ACTION_DISENGAGED = "KILL_SWITCH_DISENGAGED"


class KillSwitchReasonRequired(Exception):
    pass


def _acquire_lock(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})


def _latest_audit_event(db: Session, *, action: str) -> AuditEvent | None:
    return (
        db.query(AuditEvent)
        .filter(AuditEvent.action == action)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )


def _audit_out(event: AuditEvent | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "action": event.action,
        "actor_user_id": str(event.user_id) if event.user_id else None,
        "reason": (event.detail or {}).get("reason"),
        "occurred_at": event.created_at,
        "detail": event.detail,
    }


def _write_alerts(
    db: Session,
    *,
    actor: User,
    category: str,
    severity: str,
    title: str,
    message: str,
    metadata: dict[str, Any],
) -> None:
    """§B20 — une ligne `Alert` par contexte concerné (voir
    `_ALERTABLE_CONTEXT_KINDS`) : `Alert.execution_context_id` est NOT NULL
    (`ExecutionContextMixin`), contrairement à `EventEnvelope` (assoupli
    pour le Watchdog, D0xx) — un événement kill switch N'EST PAS
    transverse au sens du Watchdog (il concerne des stratégies et un
    trading réellement scopés par contexte), donc pas de raison de relâcher
    cette contrainte ici : on écrit une ligne par contexte concerné plutôt
    qu'une ligne globale mal typée."""
    contexts = ensure_user_contexts(db, actor)
    for kind in _ALERTABLE_CONTEXT_KINDS:
        ctx = contexts.get(kind)
        if ctx is None:  # pragma: no cover — défensif, ensure_user_contexts garantit les 3
            continue
        db.add(
            Alert(
                user_id=actor.id,
                execution_context_id=ctx.id,
                category=category,
                severity=severity,
                title=title,
                message=message,
                related_entity_type="kill_switch",
                related_entity_id=None,
                metadata_json=metadata,
            )
        )
    db.flush()


def status_detail(db: Session, redis_client) -> dict[str, Any]:
    """Lecture seule — état courant + dernier événement pertinent (engagé
    -> dernier ENGAGE, non engagé -> dernier DISENGAGE s'il existe)."""
    engaged = get_trading_kill_switch_engaged(redis_client, default=False)
    latest = _latest_audit_event(db, action=ACTION_ENGAGED if engaged else ACTION_DISENGAGED)
    return {"engaged": engaged, "last_event": _audit_out(latest)}


def history(db: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.action.in_([ACTION_ENGAGED, ACTION_DISENGAGED]))
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_audit_out(e) for e in events]


def engage(db: Session, redis_client, *, actor: User, reason: str) -> dict[str, Any]:
    if not reason or not reason.strip():
        raise KillSwitchReasonRequired()

    _acquire_lock(db)

    if get_trading_kill_switch_engaged(redis_client, default=False):
        latest = _latest_audit_event(db, action=ACTION_ENGAGED)
        return {"already_engaged": True, "engaged": True, "event": _audit_out(latest)}

    active_strategies = db.query(Strategy).filter(Strategy.status == STATUS_ACTIVE).all()
    suspended_ids: list[uuid.UUID] = [s.id for s in active_strategies]
    for strategy in active_strategies:
        strategy.status = STATUS_PAUSED

    audit = AuditEvent(
        user_id=actor.id,
        action=ACTION_ENGAGED,
        entity_type="trading",
        entity_id=None,
        detail={
            "reason": reason.strip(),
            "suspended_strategy_ids": [str(i) for i in suspended_ids],
        },
    )
    db.add(audit)
    db.flush()

    # §B20 (D078 levé — "réservé pour B20") — écrit avant le flag Redis,
    # même discipline que la ligne d'audit ci-dessus : si quoi que ce soit
    # échoue avant le flag, `get_db()` annule tout (audit ET alertes),
    # jamais un flag engagé sans trace ni notification.
    _write_alerts(
        db,
        actor=actor,
        category="kill_switch",
        severity="CRITICAL",
        title="Kill switch trading activé",
        message=f"Trading interrompu par {actor.display_name} — motif : {reason.strip()}. "
        f"{len(suspended_ids)} stratégie(s) suspendue(s).",
        metadata={"suspended_strategy_ids": [str(i) for i in suspended_ids], "reason": reason.strip()},
    )

    # Écrit en dernier, volontairement — voir docstring du module : tout
    # échec avant ce point laisse l'état précédent intact (rien n'a encore
    # réellement changé pour le Risk Engine/Order Worker/Strategy Agent).
    set_trading_kill_switch_engaged(redis_client, True)

    return {
        "already_engaged": False,
        "engaged": True,
        "event": _audit_out(audit),
        "suspended_strategy_ids": [str(i) for i in suspended_ids],
    }


def disengage(db: Session, redis_client, *, actor: User, reason: str) -> dict[str, Any]:
    if not reason or not reason.strip():
        raise KillSwitchReasonRequired()

    _acquire_lock(db)

    if not get_trading_kill_switch_engaged(redis_client, default=False):
        latest = _latest_audit_event(db, action=ACTION_DISENGAGED)
        return {"already_disengaged": True, "engaged": False, "event": _audit_out(latest)}

    audit = AuditEvent(
        user_id=actor.id,
        action=ACTION_DISENGAGED,
        entity_type="trading",
        entity_id=None,
        detail={"reason": reason.strip()},
    )
    db.add(audit)
    db.flush()

    _write_alerts(
        db,
        actor=actor,
        category="kill_switch",
        severity="INFO",
        title="Kill switch trading désactivé",
        message=f"Trading réactivé par {actor.display_name} — motif : {reason.strip()}. "
        "Aucune stratégie n'est réactivée automatiquement (reprise manuelle requise).",
        metadata={"reason": reason.strip()},
    )

    # §checklist "Récupération explicite, jamais automatique" — aucune
    # stratégie n'est réactivée ici. Elles restent PAUSED, à reprendre une
    # par une via le cycle de vie B12 existant (POST .../activate).
    set_trading_kill_switch_engaged(redis_client, False)

    return {"already_disengaged": False, "engaged": False, "event": _audit_out(audit)}
