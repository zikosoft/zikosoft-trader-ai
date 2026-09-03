"""strategy-agent — logique métier réelle (B13) : premier vrai consommateur
de `market.analysis.completed` (contrat B04, publié par le Market Agent
depuis B10, jamais consommé jusqu'ici). Pour chaque événement, charge les
`Strategy` ACTIVE du contexte d'exécution concerné, évalue chacune sur
chaque symbole surveillé et publie `strategy.proposal.created`.

Comme `market_agent/main.py` (B10), ce module n'a pas accès aux modèles ORM
de `backend` — image Docker séparée (§B01) — toutes les requêtes DB passent
par du SQL brut via `text()`, jamais par `backend.app.models`.

Verrou par stratégie/fenêtre (§B13 "empêcher proposition dupliquée" /
critère d'acceptation "une même bougie ne produit pas deux propositions
identiques") : la contrainte unique `strategy_runs(strategy_id, window_key)`
(posée dès le schéma B03) est utilisée en `INSERT ... ON CONFLICT DO
NOTHING RETURNING id` — atomique côté Postgres, aucun verrou applicatif
séparé nécessaire. `window_key` encode `<symbole>:<horodatage ISO de la
dernière bougie utilisée>` : contrairement à l'identifiant de l'événement
Redis (qui change à chaque tick du Market Agent, ~5s, indépendamment du
timeframe réel de la stratégie), l'horodatage de la DERNIÈRE BOUGIE ne
change que quand une nouvelle bougie est réellement disponible — c'est donc
la bonne granularité de "fenêtre" pour cette dédoublonnage, pas le tick lui-
même.

Sortie structurée (D022) : toute sortie d'un moteur de stratégie (déterministe
aujourd'hui, potentiellement IA demain — voir `shared/strategy_proposal.py`)
est revalidée via `StrategyProposal` avant d'être enregistrée ou publiée ; un
échec de validation ne produit jamais un crash ni une proposition non
fiable — repli HOLD explicite (voir `_build_proposal`).

**Ajout B28 (D073) : chaque proposition écrit AUSSI une ligne `agent_messages`**
(même transaction que `StrategyRun`/`AgentDecision`), complétant enfin le
"Live Debate" de l'Agent Room que la table `agent_messages` documentait déjà
depuis B03/D018 sans qu'aucun agent (hormis l'Execution & Explanation Agent,
B16) ne l'alimente. `state` vaut toujours `completed` ici — une proposition
n'est jamais elle-même "rejetée" (seul le Risk Engine, B15, rejette),
`thinking`/`failed` ne sont produits par AUCUN agent de ce pipeline (traitement
synchrone par tick, repli déterministe systématique — voir AVANCEMENT.md)."""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import socket
import uuid
from datetime import UTC, datetime
from typing import Any

import redis
from common.bootstrap import run_service
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shared.ai_governance import get_ai_calls_enabled
from shared.ai_runtime_settings import get_ai_runtime_settings, get_configured_api_key
from shared.ai_provider import AIProvider, AIProviderConfig, claude_cost_controls_from_env, get_ai_provider
from shared.eventbus import EventConsumer, publish_event
from shared.events import EventEnvelope, Streams
from shared.options import (
    OptionSelectionError,
    OptionSelectionPolicy,
    normalize_option_contracts,
    normalize_option_quotes,
    select_option_contract,
)
from shared.risk_governance import get_trading_kill_switch_engaged
from shared.strategy_proposal import StrategyProposal

logger = logging.getLogger("strategy-agent")

GROUP_NAME = "strategy-agent"
# Nom de consumer stable pour tout le cycle de vie du process (utile pour le
# suivi du PEL/dead-letter, §B04) — un process = un nom, jamais régénéré à
# chaque tick.
CONSUMER_NAME = f"strategy-agent-{socket.gethostname()}-{os.getpid()}"

READ_COUNT = 10
# Bloque peu de temps sur XREADGROUP : la cadence réelle de polling est déjà
# gouvernée par `run_service(..., interval_seconds=...)` (§common/bootstrap.py)
# — un bloc long ici retarderait inutilement le heartbeat du service.
READ_BLOCK_MS = 2000
RECLAIM_IDLE_MS = 30_000
# §B14 — nombre de clôtures récentes incluses dans `strategy.proposal.created`
# pour que le Risk Critic Agent (premier consommateur de ce stream) puisse
# calculer une volatilité récente sans réabonnement à `market.analysis.completed`.
MAX_RECENT_CLOSES = 30
OPTIONS_MAX_PREMIUM_PER_ORDER = float(os.environ.get("OPTIONS_MAX_PREMIUM_PER_ORDER", "500"))

_TYPE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_ACTIVE_STRATEGIES_SQL = text(
    """
    SELECT s.id AS strategy_id, s.definition_version, s.parameters, s.symbols, s.status,
           s.user_id, sd.type_code, sd.manifest
    FROM strategies s
    JOIN strategy_definitions sd ON sd.id = s.strategy_definition_id
    WHERE s.execution_context_id = :execution_context_id AND s.status = 'ACTIVE'
    """
)

_RUN_INSERT_SQL = text(
    """
    INSERT INTO strategy_runs
        (id, strategy_id, execution_context_id, window_key, market_data_timestamp, outcome, confidence)
    VALUES
        (:id, :strategy_id, :execution_context_id, :window_key, :market_data_timestamp, :outcome, :confidence)
    ON CONFLICT (strategy_id, window_key) DO NOTHING
    RETURNING id
    """
)

_DECISION_INSERT_SQL = text(
    """
    INSERT INTO agent_decisions
        (id, execution_context_id, strategy_id, agent_type, decision_type, outcome, confidence,
         reasoning, risk_flags, market_data_timestamp, correlation_id)
    VALUES
        (:id, :execution_context_id, :strategy_id, :agent_type, :decision_type, :outcome, :confidence,
         CAST(:reasoning AS jsonb), CAST(:risk_flags AS jsonb), :market_data_timestamp, :correlation_id)
    """
)

# §B28 (D073) — voir docstring du module.
_AGENT_MESSAGE_INSERT_SQL = text(
    """
    INSERT INTO agent_messages
        (id, user_id, execution_context_id, agent_type, conversation_thread_id, state, content, payload)
    VALUES
        (:id, :user_id, :execution_context_id, 'strategy_agent', :conversation_thread_id, :state,
         :content, CAST(:payload AS jsonb))
    """
)


def _active_strategies(engine: Engine, execution_context_id: uuid.UUID) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(_ACTIVE_STRATEGIES_SQL, {"execution_context_id": execution_context_id}).mappings().all()
    return [dict(row) for row in rows]


def _load_engine_module(type_code: str) -> Any | None:
    """Import dynamique du moteur d'une stratégie (même principe duck-typé
    que `backend/app/strategy_instances.py`, B12, pour `validate_parameters`)
    — défense en profondeur sur `type_code` avant tout `importlib.import_module`
    : une valeur corrompue en base ne doit jamais se traduire par un import
    Python arbitraire (même contrainte que `StrategyDefinition.type_code`,
    voir `shared/strategy_registry.py`)."""
    if not _TYPE_CODE_PATTERN.match(type_code or ""):
        logger.error("type_code invalide, import refusé : %r", type_code)
        return None
    try:
        return importlib.import_module(f"strategies.{type_code}.engine")
    except Exception:  # noqa: BLE001 — un moteur cassé ne doit jamais arrêter le tick
        logger.exception("échec de l'import du moteur de la stratégie %r", type_code)
        return None


def _manifest_capabilities(manifest: Any) -> list[str]:
    if not isinstance(manifest, dict):
        return []
    capabilities = manifest.get("required_capabilities")
    return capabilities if isinstance(capabilities, list) else []


def _ai_config_from_env(redis_client=None) -> AIProviderConfig:
    """§B12 "AI Market Agent Strategy" — même construction que
    `risk_critic_agent._ai_config_from_env`/`market_agent` (B10/B14) :
    dupliquée volontairement plutôt que partagée entre agents, même
    principe déjà appliqué pour `_parse_bar_timestamp` (préoccupations et
    images Docker séparées, quelques lignes sans état à synchroniser)."""
    runtime = get_ai_runtime_settings(redis_client, defaults={
        "high_stakes_model": os.environ.get("AI_MODEL_HIGH_STAKES", "claude-sonnet-4-5"),
        "low_stakes_model": os.environ.get("AI_MODEL_LOW_STAKES", "claude-haiku-4-5"),
        "max_calls_per_minute": int(os.environ.get("AI_MAX_CALLS_PER_MINUTE", "30")),
        "max_calls_per_day": int(os.environ.get("AI_MAX_CALLS_PER_DAY", "50")),
        "temperature": float(os.environ.get("AI_TEMPERATURE", "0.2")),
        "max_tokens": int(os.environ.get("AI_MAX_TOKENS", "1024")),
        "timeout_seconds": float(os.environ.get("AI_TIMEOUT_SECONDS", "20")),
        "daily_budget_usd": float(os.environ.get("AI_DAILY_BUDGET_USD", "2")),
    }, daily_budget_hard_cap_usd=float(os.environ.get("AI_DAILY_BUDGET_HARD_CAP_USD", "10"))) if redis_client is not None else {}
    return AIProviderConfig(
        high_stakes_model=runtime.get("high_stakes_model", os.environ.get("AI_MODEL_HIGH_STAKES", "claude-sonnet-4-5")),
        low_stakes_model=runtime.get("low_stakes_model", os.environ.get("AI_MODEL_LOW_STAKES", "claude-haiku-4-5")),
        max_calls_per_minute=int(runtime.get("max_calls_per_minute", os.environ.get("AI_MAX_CALLS_PER_MINUTE", "30"))),
        max_calls_per_day=int(runtime.get("max_calls_per_day", os.environ.get("AI_MAX_CALLS_PER_DAY", "500"))),
        daily_quota_client=redis_client,
        daily_budget_usd=float(runtime.get("daily_budget_usd", os.environ.get("AI_DAILY_BUDGET_USD", "2"))),
        timeout_seconds=float(runtime.get("timeout_seconds", 20.0)),
        temperature=float(runtime.get("temperature", 0.2)),
        max_tokens=int(runtime.get("max_tokens", 1024)),
        **claude_cost_controls_from_env(),
    )


def _build_ai_provider(redis_client: redis.Redis) -> AIProvider | None:
    """Construit (ou récupère depuis le cache process, voir `get_ai_provider`)
    un `AIProvider` pour les stratégies qui en ont besoin
    (`required_capabilities=["ai"]`) — appelé une fois par événement traité.
    §Correctif du 28/08 (audit B10) : jusqu'ici documenté comme une limite
    acceptée en V1 (« le quota d'appels/minute de l'instance construite ne
    survit pas au-delà de cet événement, pas un vrai quota glissant
    inter-ticks »), le même choix ayant été fait pour `risk_critic_agent`/
    `market_agent`. `get_ai_provider` (cache par clé API, durée du process)
    corrige ça sans changement de comportement métier : le quota glissant
    sur 60s (`_RateLimiter`) accumule désormais réellement son état d'un
    événement à l'autre. `None` si aucune clé API n'est configurée ou si
    l'interrupteur global IA (D026) est désactivé — les stratégies IA
    basculent alors sur leur propre repli HOLD (voir
    `strategies/ai_market_agent_strategy/engine.py`), jamais un crash."""
    config = _ai_config_from_env(redis_client)
    config.enabled = get_ai_calls_enabled(redis_client, default=os.environ.get("AI_CALLS_ENABLED", "true") == "true")
    api_key = get_configured_api_key(redis_client, fallback=os.environ.get("ANTHROPIC_API_KEY", ""))
    return get_ai_provider(api_key=api_key, config=config) if api_key else None


def _extract_bars(evidence: dict, symbol: str, timeframe: str | None) -> list[dict]:
    """§B13 — lit les bougies déjà collectées par le Market Agent
    (`evidence["bars"][symbol][timeframe]`, ajouté à B10 quand ce besoin a
    été identifié — voir `agents/market_agent/main.py`). Ne fait aucun appel
    MCP lui-même (voir docstring du module et celle de market_agent)."""
    if not timeframe:
        return []
    bars_by_symbol = evidence.get("bars") if isinstance(evidence, dict) else None
    if not isinstance(bars_by_symbol, dict):
        return []
    bars_by_timeframe = bars_by_symbol.get(symbol)
    if not isinstance(bars_by_timeframe, dict):
        return []
    bars = bars_by_timeframe.get(timeframe)
    return bars if isinstance(bars, list) else []


def _parse_bar_timestamp(raw: Any) -> datetime | None:
    """Tolérant par nécessité, même limite documentée que
    `market_agent._parse_timestamp` (non vérifiable en direct depuis cette
    sandbox — aucun accès réseau réel à Alpaca) : dupliqué volontairement
    plutôt que partagé entre les deux agents, même principe que les deux
    `_RateLimiter` distincts de B10 (préoccupations et images Docker
    séparées, une dizaine de lignes sans état à synchroniser)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float) and raw > 0:
        epoch = raw / 1000 if raw > 10**12 else float(raw)
        return datetime.fromtimestamp(epoch, tz=UTC)
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _confidence_for_signal(signal: str) -> int:
    """Convention de REPLI pour un moteur qui ne fournit pas sa propre
    confiance — les deux stratégies 100% déterministes livrées à ce jour
    (`moving_average_crossover`, `rsi_reversal`, `required_capabilities=[]`)
    n'ont pas de confiance probabiliste : 10000 (maximum, points de base)
    quand un signal univoque est détecté (BUY/SELL), 0 sinon (HOLD, aucun
    signal). Depuis B12 "AI Market Agent Strategy", un moteur qui renvoie sa
    propre `confidence` (entier 0-10000) dans son résultat brut voit cette
    valeur utilisée telle quelle par `_build_proposal` — cette fonction ne
    sert alors plus que de repli pour les moteurs qui n'en fournissent pas."""
    return 10000 if signal in ("BUY", "SELL") else 0


def _build_proposal(raw_result: Any) -> StrategyProposal:
    """Revalide la sortie brute d'un moteur de stratégie via
    `StrategyProposal` (D022) — jamais de confiance directe dans le format
    renvoyé par un module de stratégie développeur. Un échec de validation
    (bug dans le moteur, sortie inattendue) ne remonte jamais tel quel :
    repli HOLD explicite, avec le risk_flag `invalid_strategy_output` pour
    que ce cas reste visible dans l'historique (`AgentDecision`, B28/B29)
    plutôt qu'un crash silencieux du tick.

    **Trou d'architecture trouvé et corrigé en B12 (AI Market Agent
    Strategy) :** jusqu'ici cette fonction ignorait TOUJOURS `confidence`/
    `risk_flags` renvoyés par le moteur (recalcul systématique via
    `_confidence_for_signal`, `risk_flags` toujours `[]`) — invisible tant
    qu'aucun moteur ne peuplait ces champs (`moving_average_crossover`/
    `rsi_reversal` ne le font pas). Une stratégie IA a une confiance et des
    risk_flags réels (`below_min_confidence`, `requires_human_approval`,
    `ai_unavailable`, ...) qui doivent survivre jusqu'à `AgentDecision`/
    `strategy.proposal.created` — désormais utilisés quand le moteur les
    fournit dans un format valide, avec repli sur l'ancien comportement
    sinon (rétro-compatible avec les moteurs déterministes existants)."""
    if not isinstance(raw_result, dict):
        return StrategyProposal(
            signal="HOLD",
            confidence=0,
            reasoning="sortie de stratégie invalide (pas un objet) — repli HOLD de sécurité",
            risk_flags=["invalid_strategy_output"],
        )

    signal = raw_result.get("signal")
    raw_confidence = raw_result.get("confidence")
    confidence = raw_confidence if isinstance(raw_confidence, int) and 0 <= raw_confidence <= 10000 else None
    if confidence is None:
        confidence = _confidence_for_signal(signal)

    raw_risk_flags = raw_result.get("risk_flags")
    risk_flags = raw_risk_flags if isinstance(raw_risk_flags, list) and all(isinstance(f, str) for f in raw_risk_flags) else []

    try:
        return StrategyProposal(
            signal=signal,
            confidence=confidence,
            reasoning=str(raw_result.get("reasoning") or "aucun raisonnement fourni par la stratégie"),
            risk_flags=risk_flags,
            option_instrument=raw_result.get("option_instrument"),
        )
    except ValidationError as exc:
        logger.warning("sortie de stratégie invalide, repli HOLD : %s", exc)
        return StrategyProposal(
            signal="HOLD",
            confidence=0,
            reasoning=f"sortie de stratégie invalide ({exc.error_count()} erreur(s) de validation) — repli HOLD de sécurité",
            risk_flags=["invalid_strategy_output"],
        )


def _underlying_price(evidence: dict, symbol: str, bars: list[dict]) -> float | None:
    """Extract a real underlying price, preferring the latest snapshot."""
    snapshot = (evidence.get("watchlist") or {}).get(symbol)
    if isinstance(snapshot, dict):
        for container_key in ("latest_trade", "latestTrade", "latest_quote", "latestQuote", "daily_bar", "dailyBar"):
            container = snapshot.get(container_key)
            if isinstance(container, dict):
                for key in ("price", "p", "ask_price", "ap", "close", "c"):
                    value = container.get(key)
                    if isinstance(value, int | float) and float(value) > 0:
                        return float(value)
    for bar in reversed(bars):
        value = bar.get("close") if isinstance(bar, dict) else None
        if isinstance(value, int | float) and float(value) > 0:
            return float(value)
    return None


def _attach_option_instrument(
    proposal: StrategyProposal,
    *,
    evidence: dict,
    symbol: str,
    bars: list[dict],
) -> StrategyProposal:
    """Turn each directional strategy signal into a long option proposal.

    A missing/invalid chain is a safe HOLD, never a stock order. This keeps
    Replay credential-free while making the live Paper path explicit: the
    Market Agent must provide a current contract and quote before a BUY/SELL
    can reach the Risk Engine.
    """
    if proposal.signal == "HOLD" or proposal.option_instrument is not None:
        return proposal
    option_data = (evidence.get("options") or {}).get(symbol)
    if not isinstance(option_data, dict):
        option_data = {}
    contracts = normalize_option_contracts(option_data.get("contracts"), underlying_symbol=symbol)
    quotes = normalize_option_quotes(option_data.get("chain"))
    price = _underlying_price(evidence, symbol, bars)
    if not contracts or not quotes or price is None:
        return proposal.model_copy(
            update={
                "signal": "HOLD",
                "confidence": 0,
                "risk_flags": [*proposal.risk_flags, "options_unavailable"],
                "reasoning": f"signal {proposal.signal} non exécuté : chaîne options ou prix sous-jacent indisponible",
            }
        )
    try:
        instrument = select_option_contract(
            signal=proposal.signal,
            underlying_price=price,
            contracts=contracts,
            quotes=quotes,
            policy=OptionSelectionPolicy(max_premium=OPTIONS_MAX_PREMIUM_PER_ORDER),
        )
    except OptionSelectionError as exc:
        return proposal.model_copy(
            update={
                "signal": "HOLD",
                "confidence": 0,
                "risk_flags": [*proposal.risk_flags, "option_selection_failed"],
                "reasoning": f"signal {proposal.signal} non exécuté : sélection optionnelle refusée ({exc})",
            }
        )
    return proposal.model_copy(update={"option_instrument": instrument})


def _recent_closes(bars: list[dict], *, limit: int = MAX_RECENT_CLOSES) -> list[float]:
    """§B14 — extrait les dernières clôtures (déjà triées du plus ancien au
    plus récent, voir `_extract_bars`) pour que le Risk Critic Agent (premier
    consommateur) puisse évaluer la volatilité récente sans avoir à
    retraverser tout l'historique de bougies lui-même. Plafonné pour ne pas
    alourdir le payload Redis au-delà du nécessaire (une volatilité récente
    n'a pas besoin de 500 points)."""
    closes: list[float] = []
    for bar in bars[-limit:]:
        close = bar.get("close")
        if isinstance(close, int | float):
            closes.append(float(close))
    return closes


def _record_and_publish(
    engine: Engine,
    redis_client: redis.Redis,
    *,
    strategy: dict,
    symbol: str,
    proposal: StrategyProposal,
    bars: list[dict],
    market_data_timestamp: datetime,
    execution_context_id: uuid.UUID,
    user_id: uuid.UUID | None,
    correlation_id: uuid.UUID,
    causation_id: uuid.UUID,
) -> bool:
    """Enregistre `StrategyRun` + `AgentDecision` + `AgentMessage` (D073, B28)
    dans UNE transaction (cohérence : jamais l'un sans l'autre) et publie
    `strategy.proposal.created` seulement après le commit DB réussi. Retourne
    `False` sans rien publier quand `ON CONFLICT DO NOTHING` détecte que cette
    fenêtre (stratégie, symbole, dernière bougie) a déjà été traitée — c'est
    le mécanisme même de "empêcher proposition dupliquée" (§B13)."""
    window_key = f"{symbol}:{market_data_timestamp.isoformat()}"
    run_id = uuid.uuid4()
    decision_id = uuid.uuid4()

    with engine.begin() as conn:
        result = conn.execute(
            _RUN_INSERT_SQL,
            {
                "id": run_id,
                "strategy_id": strategy["strategy_id"],
                "execution_context_id": execution_context_id,
                "window_key": window_key,
                "market_data_timestamp": market_data_timestamp,
                "outcome": proposal.signal,
                "confidence": proposal.confidence,
            },
        )
        if result.first() is None:
            # Déjà traité pour cette fenêtre exacte (course entre deux ticks,
            # ou événement retraité après un redémarrage) — pas une erreur,
            # juste rien de nouveau à publier.
            logger.info(
                "proposition déjà enregistrée pour cette fenêtre, ignorée",
                extra={"strategy_id": str(strategy["strategy_id"]), "window_key": window_key},
            )
            return False

        conn.execute(
            _DECISION_INSERT_SQL,
            {
                "id": decision_id,
                "execution_context_id": execution_context_id,
                "strategy_id": strategy["strategy_id"],
                "agent_type": "strategy_agent",
                "decision_type": "PROPOSAL",
                "outcome": proposal.signal,
                "confidence": proposal.confidence,
                "reasoning": json.dumps(
                    {
                        "text": proposal.reasoning,
                        "symbol": symbol,
                        "type_code": strategy["type_code"],
                        "option_instrument": proposal.option_instrument.model_dump(mode="json")
                        if proposal.option_instrument
                        else None,
                    }
                ),
                "risk_flags": json.dumps(proposal.risk_flags),
                "market_data_timestamp": market_data_timestamp.isoformat(),
                "correlation_id": correlation_id,
            },
        )

        # §B28 (D073) — `strategy["user_id"]` (colonne NOT NULL sur
        # `strategies`, désormais sélectionnée par `_ACTIVE_STRATEGIES_SQL`)
        # est la source la plus fiable : une stratégie a toujours un
        # propriétaire, indépendamment de ce que l'événement déclencheur
        # `market.analysis.completed` transportait. Repli sur le paramètre
        # `user_id` (= `envelope.user_id`) seulement si absent, pour rester
        # robuste à un futur changement de schéma. `agent_messages.user_id`
        # est NOT NULL : jamais de ligne fabriquée avec un `user_id` inventé
        # si aucune des deux sources ne fournit de valeur.
        message_user_id = strategy.get("user_id") or user_id
        if message_user_id is not None:
            conn.execute(
                _AGENT_MESSAGE_INSERT_SQL,
                {
                    "id": uuid.uuid4(),
                    "user_id": message_user_id,
                    "execution_context_id": execution_context_id,
                    "conversation_thread_id": correlation_id,
                    "state": "completed",
                    "content": proposal.reasoning,
                    "payload": json.dumps(
                        {
                            "agent_decision_id": str(decision_id),
                            "decision_type": "PROPOSAL",
                            "outcome": proposal.signal,
                            "confidence": proposal.confidence,
                            "strategy_id": str(strategy["strategy_id"]),
                            "symbol": symbol,
                            "market_data_timestamp": market_data_timestamp.isoformat(),
                            "risk_flags": proposal.risk_flags,
                            "option_instrument": proposal.option_instrument.model_dump(mode="json")
                            if proposal.option_instrument
                            else None,
                        }
                    ),
                },
            )

    envelope = EventEnvelope(
        event_type="strategy.proposal.created",
        correlation_id=correlation_id,
        causation_id=causation_id,
        user_id=user_id,
        execution_context_id=execution_context_id,
        payload={
            "strategy_id": str(strategy["strategy_id"]),
            "type_code": strategy["type_code"],
            "definition_version": strategy["definition_version"],
            "symbol": symbol,
            "signal": proposal.signal,
            "confidence": proposal.confidence,
            "reasoning": proposal.reasoning,
            "risk_flags": proposal.risk_flags,
            "market_data_timestamp": market_data_timestamp.isoformat(),
            "window_key": window_key,
            "recent_closes": _recent_closes(bars),
            "option_instrument": proposal.option_instrument.model_dump(mode="json")
            if proposal.option_instrument
            else None,
        },
    )
    publish_event(redis_client, Streams.STRATEGY_PROPOSAL_CREATED, envelope)
    logger.info(
        "strategy.proposal.created publié",
        extra={"correlation_id": str(correlation_id), "execution_context_id": str(execution_context_id)},
    )
    return True


def _process_envelope(engine: Engine, redis_client: redis.Redis, envelope: EventEnvelope) -> None:
    payload = envelope.payload or {}

    # §B31 "Bloquer nouvelles propositions exécutables" — vérification
    # indépendante, DÉFENSE EN PROFONDEUR : `engage()` (backend/app/
    # kill_switch.py) suspend déjà (statut `PAUSED`) toutes les stratégies
    # ACTIVE au moment de l'engagement, ce qui suffit structurellement à
    # vider `_active_strategies()` ci-dessous — mais ce contrôle explicite,
    # AVANT même de lire les stratégies actives, économise en plus un appel
    # IA inutile pour la stratégie IA (`ai_market_agent_strategy`, D026) et
    # ne dépend d'aucune fenêtre de course avec la mise à jour de statut.
    # Même veto absolu que le Risk Engine (B15, `workers/risk_engine/main.py`)
    # : jamais contourné, jamais assoupli par un autre contrôle.
    if get_trading_kill_switch_engaged(redis_client, default=False):
        logger.info(
            "kill switch engagé, aucune stratégie évaluée pour cet événement",
            extra={"correlation_id": str(envelope.correlation_id)},
        )
        return

    if payload.get("stale"):
        # §B13 critère d'acceptation "données périmées -> refus clair" —
        # aucune stratégie n'est évaluée sur des données que le Market Agent
        # a lui-même signalées comme trop anciennes (§B10). Volontairement
        # pas de ligne DB pour ce cas (même principe que les erreurs d'outil
        # MCP en B10, simplement loguées) — un refus n'est pas une décision.
        logger.info(
            "données périmées, aucune stratégie évaluée pour cet événement",
            extra={"correlation_id": str(envelope.correlation_id)},
        )
        return

    evidence = payload.get("evidence") or {}
    strategies = _active_strategies(engine, envelope.execution_context_id)
    if not strategies:
        return

    # §B12 "AI Market Agent Strategy" — construit une fois par événement
    # traité, réutilisé pour toutes les stratégies IA de cet événement
    # (voir `_build_ai_provider`) ; ne coûte rien pour les événements où
    # seules des stratégies déterministes sont actives (jamais utilisé dans
    # ce cas, mais la construction elle-même ne fait aucun appel réseau).
    ai_provider = _build_ai_provider(redis_client)

    for strategy in strategies:
        capabilities = _manifest_capabilities(strategy.get("manifest"))
        requires_ai = False
        if capabilities:
            if capabilities == ["ai"]:
                # §D017/D022 — première capacité IA réellement prise en
                # charge (B12 "AI Market Agent Strategy") : la branche de
                # saut initialement prévue en B13 pour "capacité non
                # supportée" ne s'applique plus qu'aux combinaisons de
                # capacités futures et non prévues, pas à `["ai"]` seul.
                requires_ai = True
            else:
                logger.info(
                    "stratégie %r requiert des capacités non prises en charge (%s), ignorée",
                    strategy["type_code"],
                    capabilities,
                    extra={"strategy_id": str(strategy["strategy_id"])},
                )
                continue

        engine_module = _load_engine_module(strategy["type_code"])
        if engine_module is None or not hasattr(engine_module, "evaluate"):
            logger.error("moteur indisponible ou invalide pour %r, stratégie ignorée", strategy["type_code"])
            continue

        parameters = strategy.get("parameters") or {}
        timeframe = parameters.get("timeframe") if isinstance(parameters, dict) else None
        symbols = strategy.get("symbols") or []
        if not isinstance(symbols, list):
            symbols = []

        for symbol in symbols:
            bars = _extract_bars(evidence, symbol, timeframe)
            if len(bars) < 2:
                logger.debug(
                    "données insuffisantes pour %s/%s (%d bougie(s)), pas d'évaluation cette fois",
                    strategy["type_code"],
                    symbol,
                    len(bars),
                )
                continue

            market_data_timestamp = _parse_bar_timestamp(bars[-1].get("timestamp"))
            if market_data_timestamp is None:
                logger.debug("dernière bougie sans horodatage exploitable pour %s, ignorée", symbol)
                continue

            try:
                if requires_ai:
                    raw_result = engine_module.evaluate(bars, parameters, ai_provider=ai_provider, symbol=symbol)
                else:
                    raw_result = engine_module.evaluate(bars, parameters)
            except Exception:  # noqa: BLE001 — un moteur qui plante ne doit jamais arrêter le tick
                logger.exception("échec de l'évaluation de %r sur %s", strategy["type_code"], symbol)
                continue

            proposal = _build_proposal(raw_result)
            # Competition invariant: a directional signal is publishable only
            # when it carries a real, quoted option instrument. Missing chain
            # data becomes a visible HOLD instead of silently trading stock.
            proposal = _attach_option_instrument(proposal, evidence=evidence, symbol=symbol, bars=bars)

            _record_and_publish(
                engine,
                redis_client,
                strategy=strategy,
                symbol=symbol,
                proposal=proposal,
                bars=bars,
                market_data_timestamp=market_data_timestamp,
                execution_context_id=envelope.execution_context_id,
                user_id=envelope.user_id,
                correlation_id=envelope.correlation_id,
                causation_id=envelope.event_id,
            )


def tick(engine: Engine, redis_client: redis.Redis) -> None:
    consumer = EventConsumer(
        redis_client,
        stream=Streams.MARKET_ANALYSIS_COMPLETED,
        group=GROUP_NAME,
        consumer_name=CONSUMER_NAME,
    )
    consumer.ensure_group()

    for message in consumer.read(count=READ_COUNT, block_ms=READ_BLOCK_MS):
        try:
            _process_envelope(engine, redis_client, message.envelope)
            consumer.ack(message.message_id)
        except Exception:  # noqa: BLE001 — un message en échec ne doit jamais arrêter le tick (§B04 retry/dead-letter)
            logger.exception("échec du traitement d'un message market.analysis.completed")
            consumer.fail(message.message_id, message.delivery_count)

    # §B04 "reprise des messages restés en PEL" — couvre un consumer mort en
    # cours de traitement (redémarrage de conteneur, ex. `docker compose
    # down` non propre malgré le SIGTERM géré par `run_service`).
    for message in consumer.reclaim_stale(idle_ms=RECLAIM_IDLE_MS):
        try:
            _process_envelope(engine, redis_client, message.envelope)
            consumer.ack(message.message_id)
        except Exception:  # noqa: BLE001 — voir commentaire ci-dessus
            logger.exception("échec du traitement d'un message repris (PEL)")
            consumer.fail(message.message_id, message.delivery_count)


if __name__ == "__main__":
    run_service("strategy-agent", tick)
