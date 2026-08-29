"""order-worker — B17, logique métier réelle. Premier composant du pipeline
qui touche réellement l'API Alpaca en ÉCRITURE (D006 : "Order Worker seul
autorisé à exécuter" — voir `alpaca_trading_client.py` pour comment cette
règle est rendue vérifiable par simple lecture du code). Consomme
`order.command.prepared` (publié par l'Execution & Explanation Agent depuis
B16, jamais consommé jusqu'ici).

**Vérifications avant tout appel Alpaca (checklist B17), dans l'ordre :**
1. Contrat `OrderCommand` (shared.order_command) — invalide -> dead-letter
   immédiat sur `order.commands.dead-letter`, jamais un simple log ignoré
   (contrairement aux autres bricks : ici la commande porte un ORDRE réel,
   une anomalie de contrat ne doit jamais disparaître silencieusement).
2. Re-vérification indépendante que `risk_decisions.outcome == 'APPROVED'`
   (défense en profondeur, même discipline que B15 revérifiant le statut
   ACTIVE d'une stratégie plutôt que de faire confiance à l'amont).
3. Mode Paper : `execution_contexts.kind` doit être PAPER ou REPLAY (même
   politique que B15) — REPLAY est différé proprement (`deferred_replay`,
   aucun compte réel n'existe pour une simulation) ; tout le reste est
   verrouillé au niveau HTTP par `AlpacaTradingClient` (`ALPACA_PAPER_BASE_URL`,
   jamais d'option "live", même verrouillage que B07).
4. Idempotency : `idempotency_key = str(risk_decision_id)`, `client_order_id
   = f"zst-{risk_decision_id}"` — déterministes, donc stables à travers les
   retries. La ligne `orders` est insérée AVANT tout appel Alpaca et
   s'appuie sur les contraintes uniques déjà existantes du schéma
   (`uq_orders_idempotency`, `uq_orders_client_order_id`, B03) : une
   tentative en double lève `IntegrityError`, détectée et gérée
   explicitement — un dédoublonnage ATOMIQUE (contrainte DB), plus solide
   que le motif SELECT-puis-INSERT déjà signalé comme risque non-atomique
   en B14/B15/B16 (R16/R18/R19).

**"Worker redémarré pendant un ordre" (test P0) et retry transitoire
partagent le même chemin de code** : si la ligne `orders` existante est
encore `status='pending'` au moment d'un doublon détecté, on retente
`place_order()` avec le MÊME `client_order_id` plutôt que d'inventer une
réconciliation séparée — Alpaca documente que soumettre deux fois le même
`client_order_id` renvoie l'ordre existant plutôt que de l'exécuter deux
fois (voir recherche consignée en journal §39) : la déduplication finale
est donc à double niveau, DB (contrainte unique) ET Alpaca lui-même
(`client_order_id`), jamais un seul point de défaillance.

**Vérité honnête sur "Aucun ordre live possible" (test P0) : c'est le
comportement RÉEL et PERMANENT de cette V1, pas un cas limite.** B16
publie TOUJOURS `sizing_pending=true` (aucune logique de dimensionnement
d'ordre n'existe encore) — `_determine_pre_alpaca_status` court-circuite
alors systématiquement vers `blocked_sizing_pending` AVANT tout appel
Alpaca. Le chemin "placer un ordre pour de vrai" (bracket, appel HTTP,
webhooks) est entièrement écrit et testé, mais — comme le chemin
`order.command.prepared` de B16 avant lui, lui-même hérité de
l'impossibilité pour B15 de produire `APPROVED` tant que B17/B18
manquaient (D033/R17) — reste structurellement INATTEIGNABLE par le vrai
pipeline tant qu'aucune brique ne fixe `sizing_pending=false` avec un
`notional`/`quantity` réel. Testé en construisant directement un
`OrderCommand` avec `sizing_pending=false` (même principe que B16 testant
son chemin `APPROVED` par construction directe).

**Bracket order toujours bien défini en pratique (finding B17, voir
AVANCEMENT.md §37) :** une décision `APPROVED` ne peut provenir QUE d'une
stratégie déterministe (B15 impose `require_human_approval` à la
stratégie IA, ce qui bloque toujours son passage en `APPROVED`), et les
deux définitions de stratégie déterministes existantes
(`moving_average_crossover`, `rsi_reversal`) exigent `stop_loss_pct` ET
`take_profit_pct` dans leur schéma JSON (`required`). `_build_bracket_legs`
reste néanmoins défensif (jambe unique -> `order_class="oto"`, aucune
jambe -> ordre simple) plutôt que de supposer les deux toujours présentes
à l'exécution — même discipline anti-fabrication que le reste du projet.

**Écoute `trade_updates` et réconciliation REST (checklist "Consommer
updates Alpaca"/"Gérer partial fill"/"Réconcilier par REST après
reconnexion") :** un `TradeUpdatesListener` (B17,
`trade_updates_listener.py`) par compte connecté, démarré paresseusement
ici avec exactement le même motif que `McpSessionManager` dans
`market_agent` (B10) — dicts de niveau module persistants entre les
appels de `tick()`, `_ensure_listener`/`_cleanup_stale_listeners`. Ce
N'EST PAS une deuxième violation du "point unique de déchiffrement" :
`market_agent` déchiffre pour SA préoccupation (lecture MCP), ce module
déchiffre pour la sienne (écriture Alpaca, D006) — deux préoccupations
légitimes et séparées, chacune avec son propre point de déchiffrement
dédié.

**Honnêteté sur la couverture de test, comme B07/B10/B17 (client/listener)
avant ce fichier : ni le vrai endpoint Alpaca ni le vrai flux WebSocket
`trade_updates` n'ont jamais pu être exercés depuis cette sandbox** (aucun
accès réseau sortant, aucune clé réelle) — toute la logique ci-dessous est
testée contre `respx`/des doubles injectables, jamais contre Alpaca en
direct (voir AVANCEMENT.md, journal B17).

**"Annuler ordre"/"Remplacer ordre si supporté" (checklist) : satisfaits
au niveau du CLIENT** (`AlpacaTradingClient.cancel_order`/`replace_order`,
B17, déjà implémentés et testés) **mais pas encore câblés à un
consommateur ici** — aucune brique en amont ne publie encore d'événement
"annulation demandée" (probablement B18 Portefeuille ou B31 Kill switch,
tous deux listés comme dépendant de B17 dans AVANCEMENT.md). Même
discipline que le reste du projet : la capacité existe et est testée,
jamais câblée par anticipation d'un besoin qui n'existe pas encore."""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from typing import Any

import redis
from common.bootstrap import run_service
from common.encryption import decrypt_secret
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from order_worker.alpaca_trading_client import (
    AlpacaOrder,
    AlpacaOrderRejected,
    AlpacaTradingAuthError,
    AlpacaTradingClient,
    AlpacaTradingError,
)
from order_worker.trade_updates_listener import TradeUpdatesListener
from shared.eventbus import EventConsumer, publish_event
from shared.events import EventEnvelope, Streams
from shared.order_command import OrderCommand
from shared.risk_governance import get_trading_kill_switch_engaged

logger = logging.getLogger("order-worker")

GROUP_NAME = "order-worker"
CONSUMER_NAME = f"order-worker-{socket.gethostname()}-{os.getpid()}"

READ_COUNT = 10
READ_BLOCK_MS = 2000
RECLAIM_IDLE_MS = 30_000

# §checklist "Réconcilier par REST après reconnexion" — statuts Alpaca
# considérés non définitifs (un ordre dans un de ces états peut encore
# changer) ; voir `docs.alpaca.markets/us/docs/orders-at-alpaca` (recherche
# consignée en journal §39).
NON_TERMINAL_STATUSES = frozenset(
    {"pending_new", "new", "accepted", "partial_fill", "pending_cancel", "pending_replace", "calculated", "suspended"}
)

# État tenu en mémoire du process order-worker, persistant entre les appels
# de `tick()` — même motif que `_managers`/`_managers_credentials` dans
# `agents/market_agent/main.py` (B10), voir docstring du module pour
# pourquoi ce n'est pas une deuxième violation du "point unique de
# déchiffrement".
_listeners: dict[uuid.UUID, TradeUpdatesListener] = {}
_listeners_credentials: dict[uuid.UUID, tuple[str, str]] = {}

# ----------------------------------------------------------------------
# SQL
# ----------------------------------------------------------------------

_CONNECTED_ACCOUNTS_SQL = text(
    """
    SELECT uta.id AS account_id, uta.user_id, uta.encrypted_api_key, uta.encrypted_secret_key
    FROM user_trading_accounts uta
    JOIN trading_providers tp ON tp.id = uta.trading_provider_id
    WHERE tp.code = 'alpaca' AND uta.environment = 'paper' AND uta.status = 'connected'
          AND uta.encrypted_api_key IS NOT NULL AND uta.encrypted_secret_key IS NOT NULL
    """
)

_CONNECTED_TRADING_ACCOUNT_FOR_USER_SQL = text(
    """
    SELECT uta.id AS account_id, uta.encrypted_api_key, uta.encrypted_secret_key
    FROM user_trading_accounts uta
    JOIN trading_providers tp ON tp.id = uta.trading_provider_id
    WHERE tp.code = 'alpaca' AND uta.environment = 'paper' AND uta.status = 'connected'
          AND uta.user_id = :user_id
          AND uta.encrypted_api_key IS NOT NULL AND uta.encrypted_secret_key IS NOT NULL
    ORDER BY uta.created_at DESC
    LIMIT 1
    """
)

_RISK_DECISION_OUTCOME_SQL = text("SELECT outcome FROM risk_decisions WHERE id = :risk_decision_id")

_EXECUTION_CONTEXT_SQL = text("SELECT kind FROM execution_contexts WHERE id = :execution_context_id")

_ORDER_BY_IDEMPOTENCY_SQL = text(
    "SELECT id, status FROM orders WHERE execution_context_id = :execution_context_id AND idempotency_key = :idempotency_key"
)

_ORDER_BY_CLIENT_ORDER_ID_SQL = text(
    "SELECT id, execution_context_id, user_id, symbol, correlation_id, status "
    "FROM orders WHERE client_order_id = :client_order_id"
)

_NON_TERMINAL_ORDERS_FOR_USER_SQL = text(
    """
    SELECT id, execution_context_id, user_id, symbol, correlation_id, provider_order_id, client_order_id, status
    FROM orders
    WHERE user_id = :user_id AND status = ANY(:statuses) AND provider_order_id IS NOT NULL
    """
)

# §B31 "Annuler ordres ouverts éligibles" — même définition d'"éligible" que
# la réconciliation REST ci-dessus (`NON_TERMINAL_STATUSES`), mais TOUS
# utilisateurs confondus (le kill switch est global, jamais scopé par
# utilisateur ni par contexte — voir `shared/shared/risk_governance.py`).
_NON_TERMINAL_ORDERS_ALL_SQL = text(
    """
    SELECT id, execution_context_id, user_id, symbol, correlation_id, provider_order_id, client_order_id, status
    FROM orders
    WHERE status = ANY(:statuses) AND provider_order_id IS NOT NULL
    """
)

_INSERT_ORDER_SQL = text(
    """
    INSERT INTO orders
        (id, user_id, execution_context_id, strategy_id, risk_decision_id, symbol, side,
         notional, quantity, order_type, time_in_force, stop_loss, take_profit, status,
         idempotency_key, client_order_id, correlation_id)
    VALUES
        (:id, :user_id, :execution_context_id, :strategy_id, :risk_decision_id, :symbol, :side,
         :notional, :quantity, :order_type, :time_in_force, CAST(:stop_loss AS jsonb), CAST(:take_profit AS jsonb), :status,
         :idempotency_key, :client_order_id, :correlation_id)
    """
)

_UPDATE_ORDER_STATUS_SQL = text("UPDATE orders SET status = :status WHERE id = :id")

_UPDATE_ORDER_AFTER_ALPACA_SQL = text(
    """
    UPDATE orders SET status = :status, provider_order_id = :provider_order_id,
           provider_request_id = :provider_request_id, submitted_at = now()
    WHERE id = :id
    """
)

_UPDATE_ORDER_STATUS_ON_EVENT_SQL = text(
    """
    UPDATE orders SET status = :status,
           filled_at = CASE WHEN :status_check = 'fill' AND filled_at IS NULL THEN now() ELSE filled_at END
    WHERE id = :id
    """
)
# §note psycopg3 : `:status` est réutilisé deux fois ci-dessus avec des rôles
# différents (affectation vers une colonne `varchar`, comparaison à un
# littéral texte) — psycopg déduit alors deux types incompatibles pour le
# MÊME paramètre positionnel et lève `AmbiguousParameter`. Un deuxième nom
# de bind (`:status_check`, même valeur passée par l'appelant) évite le
# conflit sans recourir à un `CAST` explicite.

_ORDER_EVENT_INSERT_SQL = text(
    """
    INSERT INTO order_events (id, execution_context_id, order_id, event_type, payload, provider_request_id)
    VALUES (:id, :execution_context_id, :order_id, :event_type, CAST(:payload AS jsonb), :provider_request_id)
    """
)


# ----------------------------------------------------------------------
# Lectures
# ----------------------------------------------------------------------


def _connected_accounts(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(_CONNECTED_ACCOUNTS_SQL).mappings().all()
    return [dict(row) for row in rows]


def _fetch_connected_trading_account(engine: Engine, *, user_id: uuid.UUID) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(_CONNECTED_TRADING_ACCOUNT_FOR_USER_SQL, {"user_id": user_id}).mappings().first()
    return dict(row) if row is not None else None


def _fetch_risk_decision_outcome(engine: Engine, *, risk_decision_id: uuid.UUID) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(_RISK_DECISION_OUTCOME_SQL, {"risk_decision_id": risk_decision_id}).first()
    return row[0] if row is not None else None


def _fetch_execution_context_kind(engine: Engine, *, execution_context_id: uuid.UUID) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(_EXECUTION_CONTEXT_SQL, {"execution_context_id": execution_context_id}).first()
    return row[0] if row is not None else None


def _existing_order_by_idempotency(engine: Engine, *, execution_context_id: uuid.UUID, idempotency_key: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            _ORDER_BY_IDEMPOTENCY_SQL, {"execution_context_id": execution_context_id, "idempotency_key": idempotency_key}
        ).mappings().first()
    return dict(row) if row is not None else None


# ----------------------------------------------------------------------
# Écritures
# ----------------------------------------------------------------------


def _insert_order_event(
    engine: Engine, *, order_id: uuid.UUID, execution_context_id: uuid.UUID, event_type: str, payload: dict, provider_request_id: str | None = None
) -> None:
    with engine.begin() as conn:
        conn.execute(
            _ORDER_EVENT_INSERT_SQL,
            {
                "id": uuid.uuid4(),
                "execution_context_id": execution_context_id,
                "order_id": order_id,
                "event_type": event_type,
                "payload": json.dumps(payload, default=str),
                "provider_request_id": provider_request_id,
            },
        )


def _publish_order_status_changed(
    redis_client: redis.Redis,
    *,
    execution_context_id: uuid.UUID,
    user_id: uuid.UUID | None,
    correlation_id: uuid.UUID,
    causation_id: uuid.UUID | None,
    order_id: uuid.UUID,
    client_order_id: str,
    symbol: str,
    status: str,
    extra: dict | None = None,
) -> None:
    payload: dict[str, Any] = {"order_id": str(order_id), "client_order_id": client_order_id, "symbol": symbol, "status": status}
    if extra:
        payload.update(extra)
    envelope = EventEnvelope(
        event_type="order.status.changed",
        correlation_id=correlation_id,
        causation_id=causation_id,
        user_id=user_id,
        execution_context_id=execution_context_id,
        payload=payload,
    )
    publish_event(redis_client, Streams.ORDER_EVENTS, envelope)


def _dead_letter_invalid_command(redis_client: redis.Redis, envelope: EventEnvelope, *, reason: str) -> None:
    """§checklist "Dead-letter si commande invalide" — contrairement aux
    autres bricks (qui logguent et ignorent un payload mal formé, une
    commande d'ordre invalide ne doit jamais disparaître silencieusement :
    elle est routée explicitement vers le stream dead-letter conventionnel
    (`Streams.dead_letter`, même convention que `EventConsumer.fail`)."""
    dead_envelope = EventEnvelope(
        event_type="order.command.invalid",
        correlation_id=envelope.correlation_id,
        causation_id=envelope.event_id,
        user_id=envelope.user_id,
        execution_context_id=envelope.execution_context_id,
        payload={"reason": reason, "original_payload": envelope.payload},
    )
    publish_event(redis_client, Streams.dead_letter(Streams.ORDER_COMMANDS), dead_envelope, maxlen=None)
    logger.error(
        "commande d'ordre invalide, routée vers dead-letter",
        extra={"correlation_id": str(envelope.correlation_id), "reason": reason},
    )


# ----------------------------------------------------------------------
# Calcul des jambes bracket — pure, sans effet de bord (voir docstring du
# module pour le finding "bracket toujours bien défini en pratique").
# ----------------------------------------------------------------------


def _round_price(value: float) -> str:
    return f"{value:.2f}"


def _build_bracket_legs(command: OrderCommand) -> tuple[str | None, dict | None, dict | None]:
    """Retourne `(order_class, take_profit_leg, stop_loss_leg)` à partir de
    `reference_price`/`stop_loss_pct`/`take_profit_pct` — jamais l'inverse.
    `None`/`None`/`None` si `reference_price` est absent (rien à calculer)."""
    reference_price = command.reference_price
    if reference_price is None:
        return None, None, None

    stop_loss_leg = None
    if command.stop_loss_pct is not None:
        stop_price = (
            reference_price * (1 - command.stop_loss_pct / 100)
            if command.side == "buy"
            else reference_price * (1 + command.stop_loss_pct / 100)
        )
        stop_loss_leg = {"stop_price": _round_price(stop_price)}

    take_profit_leg = None
    if command.take_profit_pct is not None:
        limit_price = (
            reference_price * (1 + command.take_profit_pct / 100)
            if command.side == "buy"
            else reference_price * (1 - command.take_profit_pct / 100)
        )
        take_profit_leg = {"limit_price": _round_price(limit_price)}

    if stop_loss_leg and take_profit_leg:
        order_class = "bracket"
    elif stop_loss_leg or take_profit_leg:
        order_class = "oto"
    else:
        order_class = None
    return order_class, take_profit_leg, stop_loss_leg


# ----------------------------------------------------------------------
# Détermination du statut initial — avant tout appel Alpaca.
# ----------------------------------------------------------------------


def _determine_pre_alpaca_status(
    command: OrderCommand, execution_context_kind: str | None, has_account: bool, redis_client: redis.Redis
) -> str | None:
    """Retourne le statut terminal si la commande doit être bloquée AVANT
    tout appel Alpaca, ou `None` si elle est prête à être placée. Voir
    docstring du module : `blocked_sizing_pending` est en pratique le seul
    statut jamais atteint par le vrai pipeline (B16 publie toujours
    `sizing_pending=true`, "Aucun ordre live possible", test P0).

    §B31 "Bloquer Order Worker" — vérification DÉLIBÉRÉMENT en premier,
    avant même le contexte d'exécution : défense en profondeur indépendante
    du Risk Engine (B15, qui vétoie déjà toute proposition pendant que le
    kill switch est engagé — `order.command.prepared` ne devrait donc
    jamais être publié dans cette fenêtre) et du Strategy Agent (B31, qui
    cesse de son côté d'évaluer les stratégies). Un contrôle de sécurité
    financière P0 ne doit jamais reposer sur un seul point de défaillance."""
    if get_trading_kill_switch_engaged(redis_client, default=False):
        return "blocked_kill_switch"
    if execution_context_kind not in ("PAPER", "REPLAY"):
        # Ne devrait pas arriver — le Risk Engine (B15) a déjà rejeté tout
        # contexte hors PAPER/REPLAY avant de produire APPROVED — mais
        # revérifié ici en défense en profondeur, jamais une confiance
        # aveugle dans l'amont.
        return "blocked_invalid_context"
    if execution_context_kind == "REPLAY":
        # Aucun compte de trading réel n'existe pour une simulation —
        # différé proprement, jamais un appel Alpaca fantôme.
        return "deferred_replay"
    if command.sizing_pending or command.reference_price is None:
        return "blocked_sizing_pending"
    if command.notional is None and command.quantity is None:
        # Anomalie : sizing_pending=false mais ni notional ni quantity —
        # ne devrait jamais arriver tant que ce champ est fabriqué nulle
        # part, mais jamais un crash silencieux ici non plus.
        return "blocked_missing_sizing"
    if not has_account:
        return "blocked_no_trading_account"
    return None


# ----------------------------------------------------------------------
# Traitement d'une commande — chemins "bloqué" et "prêt à placer".
# ----------------------------------------------------------------------


def _process_blocked(
    engine: Engine,
    redis_client: redis.Redis,
    *,
    command: OrderCommand,
    status: str,
    execution_context_id: uuid.UUID,
    user_id: uuid.UUID,
    correlation_id: uuid.UUID,
    causation_id: uuid.UUID,
    idempotency_key: str,
    client_order_id: str,
) -> None:
    order_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            conn.execute(
                _INSERT_ORDER_SQL,
                {
                    "id": order_id,
                    "user_id": user_id,
                    "execution_context_id": execution_context_id,
                    "strategy_id": command.strategy_id,
                    "risk_decision_id": command.risk_decision_id,
                    "symbol": command.symbol,
                    "side": command.side,
                    "notional": command.notional,
                    "quantity": command.quantity,
                    "order_type": command.order_type,
                    "time_in_force": command.time_in_force,
                    "stop_loss": json.dumps({"stop_loss_pct": command.stop_loss_pct}),
                    "take_profit": json.dumps({"take_profit_pct": command.take_profit_pct}),
                    "status": status,
                    "idempotency_key": idempotency_key,
                    "client_order_id": client_order_id,
                    "correlation_id": correlation_id,
                },
            )
    except IntegrityError:
        logger.info(
            "commande déjà traitée (bloquée), doublon ignoré",
            extra={"idempotency_key": idempotency_key, "status": status},
        )
        return

    _insert_order_event(
        engine, order_id=order_id, execution_context_id=execution_context_id, event_type=f"order.{status}", payload={"reason": status}
    )
    _publish_order_status_changed(
        redis_client,
        execution_context_id=execution_context_id,
        user_id=user_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        order_id=order_id,
        client_order_id=client_order_id,
        symbol=command.symbol,
        status=status,
        extra={"reason": status},
    )
    logger.info("commande bloquée avant tout appel Alpaca", extra={"correlation_id": str(correlation_id), "status": status})


def _process_ready_to_place(
    engine: Engine,
    redis_client: redis.Redis,
    *,
    command: OrderCommand,
    execution_context_id: uuid.UUID,
    user_id: uuid.UUID,
    correlation_id: uuid.UUID,
    causation_id: uuid.UUID,
    idempotency_key: str,
    client_order_id: str,
    api_key: str,
    secret_key: str,
) -> None:
    order_class, take_profit_leg, stop_loss_leg = _build_bracket_legs(command)

    order_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            conn.execute(
                _INSERT_ORDER_SQL,
                {
                    "id": order_id,
                    "user_id": user_id,
                    "execution_context_id": execution_context_id,
                    "strategy_id": command.strategy_id,
                    "risk_decision_id": command.risk_decision_id,
                    "symbol": command.symbol,
                    "side": command.side,
                    "notional": command.notional,
                    "quantity": command.quantity,
                    "order_type": command.order_type,
                    "time_in_force": command.time_in_force,
                    "stop_loss": json.dumps({"stop_loss_pct": command.stop_loss_pct, "leg": stop_loss_leg}),
                    "take_profit": json.dumps({"take_profit_pct": command.take_profit_pct, "leg": take_profit_leg}),
                    "status": "pending",
                    "idempotency_key": idempotency_key,
                    "client_order_id": client_order_id,
                    "correlation_id": correlation_id,
                },
            )
    except IntegrityError:
        existing = _existing_order_by_idempotency(engine, execution_context_id=execution_context_id, idempotency_key=idempotency_key)
        if existing is None:
            logger.error("doublon détecté mais ligne introuvable, anomalie", extra={"idempotency_key": idempotency_key})
            return
        if existing["status"] != "pending":
            logger.info(
                "commande déjà traitée (statut %s), doublon ignoré", existing["status"], extra={"idempotency_key": idempotency_key}
            )
            return
        # §test P0 "Worker redémarré pendant un ordre" — la ligne existe
        # déjà en 'pending' : on ne sait pas si Alpaca l'a reçue avant
        # l'interruption. Retente avec le MÊME client_order_id — Alpaca
        # lui-même déduplique dessus (voir docstring du module).
        order_id = existing["id"]
        logger.warning(
            "ordre 'pending' déjà existant détecté — nouvelle tentative avec le même client_order_id",
            extra={"order_id": str(order_id), "correlation_id": str(correlation_id)},
        )

    client = AlpacaTradingClient(api_key, secret_key)
    try:
        alpaca_order: AlpacaOrder = client.place_order(
            symbol=command.symbol,
            side=command.side,
            client_order_id=client_order_id,
            order_type=command.order_type,
            time_in_force=command.time_in_force,
            qty=command.quantity,
            notional=command.notional,
            order_class=order_class,
            take_profit=take_profit_leg,
            stop_loss=stop_loss_leg,
        )
    except AlpacaOrderRejected as exc:
        # §test P0 "Ordre rejeté Alpaca"/"Fonds insuffisants" — résultat
        # métier attendu, terminal, jamais retenté.
        with engine.begin() as conn:
            conn.execute(_UPDATE_ORDER_STATUS_SQL, {"id": order_id, "status": "rejected"})
        _insert_order_event(
            engine,
            order_id=order_id,
            execution_context_id=execution_context_id,
            event_type="order.rejected",
            payload={"message": str(exc), "code": exc.code},
        )
        _publish_order_status_changed(
            redis_client,
            execution_context_id=execution_context_id,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=command.symbol,
            status="rejected",
            extra={"message": str(exc), "code": exc.code},
        )
        logger.warning("ordre rejeté par Alpaca : %s", exc, extra={"correlation_id": str(correlation_id)})
        return
    except AlpacaTradingAuthError as exc:
        # Identifiants refusés — systémique, pas transitoire : retenter le
        # même message ne le résoudrait pas, terminal ici aussi.
        with engine.begin() as conn:
            conn.execute(_UPDATE_ORDER_STATUS_SQL, {"id": order_id, "status": "error_auth"})
        _insert_order_event(
            engine, order_id=order_id, execution_context_id=execution_context_id, event_type="order.error_auth", payload={"message": str(exc)}
        )
        _publish_order_status_changed(
            redis_client,
            execution_context_id=execution_context_id,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=command.symbol,
            status="error_auth",
            extra={"message": str(exc)},
        )
        logger.error("identifiants Alpaca refusés lors de la soumission d'un ordre : %s", exc, extra={"correlation_id": str(correlation_id)})
        return
    # AlpacaTradingUpstreamError volontairement PAS capturée ici : transitoire
    # (timeout, 5xx), elle remonte jusqu'à `tick()` qui la traite via le
    # retry/dead-letter standard de `EventConsumer.fail` (§B04). La ligne
    # `orders` reste 'pending' — au prochain passage, le doublon détecté
    # ci-dessus retentera avec le même client_order_id (même chemin que
    # "Worker redémarré pendant un ordre").

    with engine.begin() as conn:
        conn.execute(
            _UPDATE_ORDER_AFTER_ALPACA_SQL,
            {
                "id": order_id,
                "status": alpaca_order.status,
                "provider_order_id": alpaca_order.id,
                "provider_request_id": alpaca_order.request_id,
            },
        )
    _insert_order_event(
        engine,
        order_id=order_id,
        execution_context_id=execution_context_id,
        event_type=f"order.{alpaca_order.status}",
        payload=alpaca_order.raw,
        provider_request_id=alpaca_order.request_id,
    )
    _publish_order_status_changed(
        redis_client,
        execution_context_id=execution_context_id,
        user_id=user_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        order_id=order_id,
        client_order_id=client_order_id,
        symbol=command.symbol,
        status=alpaca_order.status,
        extra={"provider_order_id": alpaca_order.id},
    )
    logger.info(
        "ordre soumis à Alpaca",
        extra={"correlation_id": str(correlation_id), "status": alpaca_order.status, "provider_order_id": alpaca_order.id},
    )


def _process_envelope(engine: Engine, redis_client: redis.Redis, envelope: EventEnvelope) -> None:
    try:
        command = OrderCommand(**(envelope.payload or {}))
    except ValidationError as exc:
        _dead_letter_invalid_command(redis_client, envelope, reason=f"contrat OrderCommand invalide : {exc}")
        return

    risk_outcome = _fetch_risk_decision_outcome(engine, risk_decision_id=command.risk_decision_id)
    if risk_outcome != "APPROVED":
        # Ne devrait jamais arriver (B16 ne prépare une commande que pour
        # APPROVED) — anomalie signalée, jamais une exécution sur la base
        # d'une confiance aveugle dans l'amont (même discipline que la
        # revérification ACTIVE en B15).
        logger.error(
            "décision de risque non APPROVED au moment du traitement (%r) — commande abandonnée, anomalie",
            risk_outcome,
            extra={"risk_decision_id": str(command.risk_decision_id)},
        )
        return

    execution_context_id = envelope.execution_context_id
    user_id = envelope.user_id
    if user_id is None:
        logger.error("commande sans user_id, abandonnée (anomalie)", extra={"correlation_id": str(envelope.correlation_id)})
        return

    execution_context_kind = _fetch_execution_context_kind(engine, execution_context_id=execution_context_id)

    idempotency_key = str(command.risk_decision_id)
    client_order_id = f"zst-{command.risk_decision_id}"

    account = None
    if execution_context_kind == "PAPER":
        account = _fetch_connected_trading_account(engine, user_id=user_id)

    status = _determine_pre_alpaca_status(command, execution_context_kind, account is not None, redis_client)

    if status is not None:
        _process_blocked(
            engine,
            redis_client,
            command=command,
            status=status,
            execution_context_id=execution_context_id,
            user_id=user_id,
            correlation_id=envelope.correlation_id,
            causation_id=envelope.event_id,
            idempotency_key=idempotency_key,
            client_order_id=client_order_id,
        )
        return

    assert account is not None  # garanti par _determine_pre_alpaca_status (has_account=True)
    try:
        api_key = decrypt_secret(account["encrypted_api_key"])
        secret_key = decrypt_secret(account["encrypted_secret_key"])
    except Exception:  # noqa: BLE001 — jamais logué en détail (pourrait fuiter des infos sur la clé)
        logger.exception("échec de déchiffrement des identifiants du compte de trading, commande abandonnée")
        return

    _process_ready_to_place(
        engine,
        redis_client,
        command=command,
        execution_context_id=execution_context_id,
        user_id=user_id,
        correlation_id=envelope.correlation_id,
        causation_id=envelope.event_id,
        idempotency_key=idempotency_key,
        client_order_id=client_order_id,
        api_key=api_key,
        secret_key=secret_key,
    )


# ----------------------------------------------------------------------
# Écoute trade_updates + réconciliation REST — un TradeUpdatesListener par
# compte connecté, motif identique à McpSessionManager (market_agent, B10).
# ----------------------------------------------------------------------


def _apply_trade_update_event(engine: Engine, redis_client: redis.Redis, event: dict) -> None:
    """Callback `on_event` du `TradeUpdatesListener` — appelé depuis le
    thread dédié du listener, jamais depuis `tick()` (voir docstring de
    `trade_updates_listener.py`). SQLAlchemy Engine est thread-safe pour cet
    usage (chaque appel emprunte sa propre connexion au pool)."""
    order_data = event.get("order") or {}
    client_order_id = order_data.get("client_order_id")
    if not client_order_id:
        logger.warning("événement trade_updates sans client_order_id, ignoré")
        return

    with engine.connect() as conn:
        row = conn.execute(_ORDER_BY_CLIENT_ORDER_ID_SQL, {"client_order_id": client_order_id}).mappings().first()
    if row is None:
        logger.warning("événement trade_updates pour un ordre inconnu localement, ignoré", extra={"client_order_id": client_order_id})
        return
    order = dict(row)

    new_status = event.get("event") or "unknown"
    with engine.begin() as conn:
        conn.execute(_UPDATE_ORDER_STATUS_ON_EVENT_SQL, {"id": order["id"], "status": new_status, "status_check": new_status})
    _insert_order_event(
        engine, order_id=order["id"], execution_context_id=order["execution_context_id"], event_type=f"order.{new_status}", payload=event
    )
    _publish_order_status_changed(
        redis_client,
        execution_context_id=order["execution_context_id"],
        user_id=order["user_id"],
        correlation_id=order["correlation_id"],
        causation_id=None,
        order_id=order["id"],
        client_order_id=client_order_id,
        symbol=order["symbol"],
        status=new_status,
        extra={"source": "websocket"},
    )
    logger.info("statut d'ordre mis à jour via WebSocket trade_updates", extra={"client_order_id": client_order_id, "status": new_status})


def _cancel_orders_for_kill_switch(engine: Engine, redis_client: redis.Redis, accounts: list[dict]) -> None:
    """§B31 "Annuler ordres ouverts éligibles après confirmation" — appelée
    à CHAQUE tick tant que le flag reste engagé (voir `tick()` ci-dessous),
    pas seulement une fois à l'instant de l'engagement : idempotente par
    construction (un ordre déjà `pending_cancel`/terminal ne réapparaît plus
    dans `_NON_TERMINAL_ORDERS_ALL_SQL`), ce qui rattrape aussi tout ordre
    qui serait passé "ouvert" juste après l'engagement (course avec un appel
    Alpaca déjà en vol au moment du bascule du flag).

    Respecte D006/D037 ("Order Worker seul autorisé à exécuter") : c'est le
    SEUL endroit du projet qui annule un ordre pour de vrai — le backend
    (`backend/app/kill_switch.py::engage`) ne fait que suspendre les
    stratégies et poser le flag, jamais un appel Alpaca lui-même.

    **Honnêteté sur la portée réelle en V1 (voir D040, AVANCEMENT.md) :**
    B16 publie aujourd'hui TOUJOURS `sizing_pending=true`, donc AUCUN ordre
    n'atteint jamais `provider_order_id IS NOT NULL` par le vrai pipeline —
    ce balayage ne trouve donc structurellement rien à annuler tant que ce
    verrou amont n'est pas levé par une future brique de dimensionnement.
    Le chemin est néanmoins écrit et testé en entier, par construction
    directe d'une ligne `orders` déjà "ouverte" — même principe exact que
    B16/B17 testant leurs propres chemins autrement inatteignables."""
    with engine.connect() as conn:
        rows = conn.execute(_NON_TERMINAL_ORDERS_ALL_SQL, {"statuses": list(NON_TERMINAL_STATUSES)}).mappings().all()
    if not rows:
        return

    creds_by_user = {a["user_id"]: (a["encrypted_api_key"], a["encrypted_secret_key"]) for a in accounts}

    for row in rows:
        order = dict(row)
        creds = creds_by_user.get(order["user_id"])
        if creds is None:
            logger.warning(
                "kill switch : ordre ouvert sans compte de trading connecté correspondant, annulation impossible",
                extra={"order_id": str(order["id"])},
            )
            continue
        try:
            api_key = decrypt_secret(creds[0])
            secret_key = decrypt_secret(creds[1])
        except Exception:  # noqa: BLE001 — jamais logué en détail (pourrait fuiter des infos sur la clé)
            logger.exception("kill switch : échec de déchiffrement des identifiants pour l'annulation d'un ordre")
            continue

        client = AlpacaTradingClient(api_key, secret_key)
        try:
            client.cancel_order(order["provider_order_id"])
        except AlpacaOrderRejected as exc:
            # §probablement déjà terminal côté Alpaca entre notre lecture et
            # cet appel (fill/cancel/expire concurrent) — pas une anomalie,
            # la prochaine réconciliation REST/WebSocket rattrapera le
            # statut réel, aucune tentative supplémentaire ici.
            logger.info(
                "kill switch : annulation refusée par Alpaca (probablement déjà terminal)",
                extra={"order_id": str(order["id"]), "error": str(exc)},
            )
            continue
        except AlpacaTradingError as exc:
            logger.warning(
                "kill switch : échec d'annulation d'un ordre ouvert", extra={"order_id": str(order["id"]), "error": str(exc)}
            )
            continue

        with engine.begin() as conn:
            conn.execute(_UPDATE_ORDER_STATUS_ON_EVENT_SQL, {"id": order["id"], "status": "pending_cancel", "status_check": "pending_cancel"})
        _insert_order_event(
            engine,
            order_id=order["id"],
            execution_context_id=order["execution_context_id"],
            event_type="order.cancel_requested",
            payload={"reason": "kill_switch"},
        )
        _publish_order_status_changed(
            redis_client,
            execution_context_id=order["execution_context_id"],
            user_id=order["user_id"],
            correlation_id=order["correlation_id"],
            causation_id=None,
            order_id=order["id"],
            client_order_id=order["client_order_id"],
            symbol=order["symbol"],
            status="pending_cancel",
            extra={"reason": "kill_switch"},
        )
        logger.info("kill switch : annulation demandée pour un ordre ouvert", extra={"order_id": str(order["id"])})


def _reconcile_after_reconnect(engine: Engine, redis_client: redis.Redis, *, user_id: uuid.UUID, api_key: str, secret_key: str) -> None:
    """§checklist "Réconcilier par REST après reconnexion" — déclenché par
    `TradeUpdatesListener.on_reconnected` (jamais à la toute première
    connexion, voir sa docstring). Toute transition manquée pendant une
    coupure WebSocket est rattrapée ici via l'API REST (source de vérité),
    pour chaque ordre localement non-terminal de cet utilisateur."""
    with engine.connect() as conn:
        rows = conn.execute(
            _NON_TERMINAL_ORDERS_FOR_USER_SQL, {"user_id": user_id, "statuses": list(NON_TERMINAL_STATUSES)}
        ).mappings().all()
    if not rows:
        return

    client = AlpacaTradingClient(api_key, secret_key)
    for row in rows:
        order = dict(row)
        try:
            alpaca_order = client.get_order(order["provider_order_id"])
        except AlpacaTradingError as exc:
            logger.warning("réconciliation REST échouée pour un ordre : %s", exc, extra={"order_id": str(order["id"])})
            continue
        if alpaca_order.status == order.get("status"):
            continue
        with engine.begin() as conn:
            conn.execute(
                _UPDATE_ORDER_STATUS_ON_EVENT_SQL,
                {"id": order["id"], "status": alpaca_order.status, "status_check": alpaca_order.status},
            )
        _insert_order_event(
            engine,
            order_id=order["id"],
            execution_context_id=order["execution_context_id"],
            event_type=f"order.{alpaca_order.status}",
            payload=alpaca_order.raw,
            provider_request_id=alpaca_order.request_id,
        )
        _publish_order_status_changed(
            redis_client,
            execution_context_id=order["execution_context_id"],
            user_id=order["user_id"],
            correlation_id=order["correlation_id"],
            causation_id=None,
            order_id=order["id"],
            client_order_id=order["client_order_id"],
            symbol=order["symbol"],
            status=alpaca_order.status,
            extra={"source": "reconciliation_rest"},
        )
        logger.info("ordre réconcilié par REST après reconnexion", extra={"order_id": str(order["id"]), "status": alpaca_order.status})


def _ensure_listener(account_id: uuid.UUID, user_id: uuid.UUID, api_key: str, secret_key: str, *, engine: Engine, redis_client: redis.Redis) -> TradeUpdatesListener:
    creds = (api_key, secret_key)
    listener = _listeners.get(account_id)
    if listener is None:

        def _on_event(event: dict) -> None:
            _apply_trade_update_event(engine, redis_client, event)

        def _on_reconnected() -> None:
            _reconcile_after_reconnect(engine, redis_client, user_id=user_id, api_key=api_key, secret_key=secret_key)

        listener = TradeUpdatesListener(on_event=_on_event, on_reconnected=_on_reconnected)
        _listeners[account_id] = listener
        listener.start(api_key, secret_key)
        _listeners_credentials[account_id] = creds
    elif _listeners_credentials.get(account_id) != creds:
        logger.info("account %s: identifiants modifiés, redémarrage de l'écoute trade_updates", account_id)
        listener.stop()
        listener.start(api_key, secret_key)
        _listeners_credentials[account_id] = creds
    return listener


def _cleanup_stale_listeners(active_account_ids: set[uuid.UUID]) -> None:
    for account_id in list(_listeners):
        if account_id not in active_account_ids:
            logger.info("account %s: plus connecté, arrêt de l'écoute trade_updates", account_id)
            _listeners.pop(account_id).stop()
            _listeners_credentials.pop(account_id, None)


def tick(engine: Engine, redis_client: redis.Redis) -> None:
    accounts = _connected_accounts(engine)
    active_ids = {a["account_id"] for a in accounts}
    _cleanup_stale_listeners(active_ids)

    # §B31 "Annuler ordres ouverts éligibles" — balayé à CHAQUE tick tant
    # que le flag reste engagé (voir docstring de `_cancel_orders_for_kill_switch`).
    # Une erreur ici ne doit jamais empêcher le reste du tick (écoute
    # trade_updates, traitement des commandes en attente) — même discipline
    # que partout ailleurs dans ce fichier (§B04 "un échec ne doit jamais
    # arrêter le tick").
    if get_trading_kill_switch_engaged(redis_client, default=False):
        try:
            _cancel_orders_for_kill_switch(engine, redis_client, accounts)
        except Exception:  # noqa: BLE001 — voir commentaire ci-dessus
            logger.exception("échec du balayage d'annulation kill switch")

    for account in accounts:
        account_id = account["account_id"]
        try:
            api_key = decrypt_secret(account["encrypted_api_key"])
            secret_key = decrypt_secret(account["encrypted_secret_key"])
        except Exception:  # noqa: BLE001 — jamais logué en détail (pourrait fuiter des infos sur la clé)
            logger.exception("account %s: échec de déchiffrement des identifiants (écoute trade_updates)", account_id)
            continue
        _ensure_listener(account_id, account["user_id"], api_key, secret_key, engine=engine, redis_client=redis_client)

    consumer = EventConsumer(redis_client, stream=Streams.ORDER_COMMANDS, group=GROUP_NAME, consumer_name=CONSUMER_NAME)
    consumer.ensure_group()

    for message in consumer.read(count=READ_COUNT, block_ms=READ_BLOCK_MS):
        try:
            _process_envelope(engine, redis_client, message.envelope)
            consumer.ack(message.message_id)
        except Exception:  # noqa: BLE001 — un message en échec ne doit jamais arrêter le tick (§B04 retry/dead-letter)
            logger.exception("échec du traitement d'une commande d'ordre")
            consumer.fail(message.message_id, message.delivery_count)

    for message in consumer.reclaim_stale(idle_ms=RECLAIM_IDLE_MS):
        try:
            _process_envelope(engine, redis_client, message.envelope)
            consumer.ack(message.message_id)
        except Exception:  # noqa: BLE001 — voir commentaire ci-dessus
            logger.exception("échec du traitement d'une commande reprise (PEL)")
            consumer.fail(message.message_id, message.delivery_count)


if __name__ == "__main__":
    run_service("order-worker", tick)
