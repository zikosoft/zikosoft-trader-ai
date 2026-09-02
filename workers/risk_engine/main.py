"""risk-engine — B15, pipeline de règles déterministe (§D005 : composant
NON-IA, dernier mot sur toute proposition, ne peut jamais être contourné
par un agent). Consomme `risk.critique.completed` (publié par le Risk
Critic Agent depuis B14 — jamais consommé jusqu'ici), applique une série de
contrôles déterministes, et publie `risk.validation.completed`.

Comme `market_agent`/`strategy_agent`/`risk_critic_agent` (B10/B13/B14), ce
module n'a pas accès aux modèles ORM de `backend` (image Docker séparée,
§B01) — tout passe par du SQL brut via `text()`.

**Discipline anti-fabrication (même esprit que B14) : les contrôles sont
évalués à chaque décision, TOUS, jamais un sous-ensemble silencieusement
sauté.** Les contrôles communs s'appuient sur des données réellement disponibles
aujourd'hui (contexte, compte, statut stratégie, fraîcheur, limites de
compte, protection obligatoire, doublon, cooldown, kill switch, politique
d'approbation). **5 ne peuvent PAS être vérifiés honnêtement — pas
seulement "tant que B18 n'existe pas" (correction du 26/08, voir D042
§37/§39)** : argent disponible, notional, exposition par symbole,
exposition totale, perte quotidienne. B18 (Portefeuille) écrit désormais de
vrais `portfolio_snapshots`/`positions_snapshots`, mais ça ne change RIEN à
ces 5 constats — la donnée existe, la LIMITE à laquelle la comparer
n'existe toujours nulle part dans le système (pas de daily-loss-limit, pas
d'exposure-limit, pas de comparaison notional-vs-buying-power). Ces 5
contrôles sont donc INCONDITIONNELS (indépendants de la présence ou non
d'un snapshot), et le déclarent explicitement "impossible à vérifier", ce
qui force au minimum un `REQUIRES_APPROVAL` — jamais un `APPROVED`
silencieux sur une limite qui n'existe pas.

**Pour les commandes equity**, les cinq limites historiquement absentes
restent `REQUIRES_APPROVAL` comme avant. **Pour une commande option**, le
contrat contient déjà une prime, une quantité et une perte maximale : les
contrôles dédiés les vérifient contre les limites Paper configurées et le
snapshot de buying power, sans relâcher le kill switch ni les contrôles
communs. Ainsi un ordre optionnel peut devenir `APPROVED` uniquement quand
les preuves nécessaires sont présentes.

**`ADJUSTED` n'est jamais produit par cette V1** (voir
`shared.risk_decision`) — le dimensionnement options est calculé par le
sélecteur partagé puis revalidé ici, sans ajustement silencieux.

**Ajout B28 (D073) : chaque décision écrit AUSSI une ligne `agent_messages`**
(même transaction que `RiskDecision`) — même principe que
`agents/strategy_agent/main.py`/`agents/risk_critic_agent/main.py`, complétant
le "Live Debate" de l'Agent Room avec le SEUL maillon non-IA du pipeline
(`agent_type = "risk_engine"`, délibérément distinct de `*_agent`, D029 :
vocabulaire différent entre critique IA consultative et décision de risque
contraignante). Contenu déterministe (gabarit fixe par `outcome`, jamais
d'appel IA — ce module reste strictement non-IA)."""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from datetime import UTC, datetime
from typing import Any

import redis
from common.bootstrap import run_service
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shared.eventbus import EventConsumer, publish_event
from shared.events import EventEnvelope, Streams
from shared.options import OptionInstrument
from shared.risk_decision import RiskDecisionResult
from shared.risk_governance import get_trading_kill_switch_engaged

logger = logging.getLogger("risk-engine")

GROUP_NAME = "risk-engine"
CONSUMER_NAME = f"risk-engine-{socket.gethostname()}-{os.getpid()}"

READ_COUNT = 10
READ_BLOCK_MS = 2000
RECLAIM_IDLE_MS = 30_000

# §B15 "Examiner fraîcheur des données" — même seuil que B10/B13/B14
# (`MAX_EVIDENCE_AGE_SECONDS`/`MAX_PROPOSAL_AGE_SECONDS`), revérifié
# indépendamment ici plutôt que de faire confiance aveuglément au filtrage
# déjà fait en amont par le Risk Critic Agent.
MAX_CRITIQUE_AGE_SECONDS = 15 * 60

# §B15 "Cooldown" — délai minimum entre deux décisions de risque pour une
# même stratégie, configurable (voir .env.example).
COOLDOWN_SECONDS = int(os.environ.get("RISK_ENGINE_COOLDOWN_SECONDS", "60"))

# Conservative, server-side limits for the one-leg long-options demo. These
# are deliberately independent from Claude/AI budgets and from the existing
# equity controls. They can be tightened in the Paper environment without a
# code change.
OPTIONS_MAX_PREMIUM_PER_ORDER = float(os.environ.get("OPTIONS_MAX_PREMIUM_PER_ORDER", "500"))
OPTIONS_MAX_CONTRACTS = int(os.environ.get("OPTIONS_MAX_CONTRACTS", "1"))
OPTIONS_MAX_SPREAD_PCT = float(os.environ.get("OPTIONS_MAX_SPREAD_PCT", "0.20"))
OPTIONS_MIN_DTE = int(os.environ.get("OPTIONS_MIN_DTE", "7"))
OPTIONS_MAX_DTE = int(os.environ.get("OPTIONS_MAX_DTE", "30"))

# Dupliqués depuis `backend/app/strategy_instances.py` (même pattern que
# B14/`_concentration_others` — re-vérification en défense en profondeur,
# indépendante des limites déjà posées côté CRUD, pas une confiance
# aveugle dans le fait qu'elles n'ont jamais pu être contournées).
MAX_ACTIVE_STRATEGIES = 3
MAX_CUMULATIVE_SYMBOLS = 10

AI_STRATEGY_TYPE_CODE = "ai_market_agent_strategy"

REJECTED = "REJECTED"
REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
APPROVED = "APPROVED"

_TIER_PRECEDENCE = {REJECTED: 2, REQUIRES_APPROVAL: 1}

_CRITIQUE_DECISION_SQL = text(
    """
    SELECT id FROM agent_decisions
    WHERE decision_type = 'CRITIQUE'
      AND strategy_id = :strategy_id
      AND reasoning->>'symbol' = :symbol
      AND market_data_timestamp = :market_data_timestamp
    ORDER BY created_at DESC
    LIMIT 1
    """
)

_EXISTING_RISK_DECISION_SQL = text(
    "SELECT 1 FROM risk_decisions WHERE agent_decision_id = :agent_decision_id LIMIT 1"
)

_STRATEGY_SQL = text(
    """
    SELECT s.id AS strategy_id, s.status, s.parameters, s.execution_context_id, s.user_id,
           sd.type_code
    FROM strategies s
    JOIN strategy_definitions sd ON sd.id = s.strategy_definition_id
    WHERE s.id = :strategy_id
    """
)

_EXECUTION_CONTEXT_SQL = text("SELECT kind FROM execution_contexts WHERE id = :execution_context_id")

_TRADING_ACCOUNT_SQL = text(
    """
    SELECT status FROM user_trading_accounts
    WHERE user_id = :user_id AND is_default = true
    ORDER BY created_at DESC
    LIMIT 1
    """
)

_ACTIVE_STRATEGIES_SQL = text(
    "SELECT id, symbols FROM strategies WHERE execution_context_id = :execution_context_id AND status = 'ACTIVE'"
)

_LAST_RISK_DECISION_SQL = text(
    """
    SELECT rd.created_at
    FROM risk_decisions rd
    JOIN agent_decisions ad ON ad.id = rd.agent_decision_id
    WHERE ad.strategy_id = :strategy_id
    ORDER BY rd.created_at DESC
    LIMIT 1
    """
)

_PORTFOLIO_SNAPSHOT_SQL = text(
    """
    SELECT 1 FROM portfolio_snapshots
    WHERE execution_context_id = :execution_context_id
    ORDER BY snapshot_at DESC
    LIMIT 1
    """
)

_POSITION_SNAPSHOT_SQL = text(
    """
    SELECT 1 FROM positions_snapshots
    WHERE execution_context_id = :execution_context_id AND symbol = :symbol
    ORDER BY snapshot_at DESC
    LIMIT 1
    """
)

_LATEST_PORTFOLIO_RISK_SQL = text(
    """
    SELECT buying_power, daily_pl
    FROM portfolio_snapshots
    WHERE execution_context_id = :execution_context_id
    ORDER BY snapshot_at DESC
    LIMIT 1
    """
)

_DECISION_INSERT_SQL = text(
    """
    INSERT INTO risk_decisions
        (id, execution_context_id, agent_decision_id, outcome, reasons, adjustments, correlation_id)
    VALUES
        (:id, :execution_context_id, :agent_decision_id, :outcome,
         CAST(:reasons AS jsonb), CAST(:adjustments AS jsonb), :correlation_id)
    """
)

# §B28 (D073) — voir docstring du module.
_AGENT_MESSAGE_INSERT_SQL = text(
    """
    INSERT INTO agent_messages
        (id, user_id, execution_context_id, agent_type, conversation_thread_id, state, content, payload)
    VALUES
        (:id, :user_id, :execution_context_id, 'risk_engine', :conversation_thread_id, :state,
         :content, CAST(:payload AS jsonb))
    """
)

_RISK_ENGINE_OUTCOME_LABELS = {
    "APPROVED": "Ordre approuvé sans réserve.",
    "ADJUSTED": "Ordre approuvé avec ajustement.",
    "REQUIRES_APPROVAL": "Validation humaine requise avant exécution.",
    "REJECTED": "Ordre rejeté.",
}


def _agent_message_content(outcome: str, reasons: list[str]) -> str:
    """Gabarit déterministe (jamais d'appel IA — ce module reste
    strictement non-IA, D005) — même esprit que `_fallback_explanation`
    (B16, `agents/execution_explanation_agent/main.py`)."""
    text_content = _RISK_ENGINE_OUTCOME_LABELS.get(outcome, f"Décision : {outcome}.")
    if reasons:
        text_content += " Raison principale : " + reasons[0]
    return text_content


def _parse_iso_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _find_critique_agent_decision_id(
    engine: Engine, *, strategy_id: uuid.UUID, symbol: str, market_data_timestamp: str
) -> uuid.UUID | None:
    with engine.connect() as conn:
        row = conn.execute(
            _CRITIQUE_DECISION_SQL,
            {"strategy_id": strategy_id, "symbol": symbol, "market_data_timestamp": market_data_timestamp},
        ).first()
    return row[0] if row is not None else None


def _already_decided(engine: Engine, *, agent_decision_id: uuid.UUID) -> bool:
    """Garde-fou anti-doublon — même esprit et mêmes limites que
    `risk_critic_agent._already_critiqued` (non atomique, voir sa
    docstring) : `agent_decision_id` est la clé naturelle ici (une seule
    décision de risque par critique, contrainte FK NOT NULL sur
    `risk_decisions.agent_decision_id`)."""
    with engine.connect() as conn:
        row = conn.execute(_EXISTING_RISK_DECISION_SQL, {"agent_decision_id": agent_decision_id}).first()
    return row is not None


def _fetch_strategy(engine: Engine, *, strategy_id: uuid.UUID) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(_STRATEGY_SQL, {"strategy_id": strategy_id}).mappings().first()
    return dict(row) if row is not None else None


def _fetch_execution_context_kind(engine: Engine, *, execution_context_id: uuid.UUID) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(_EXECUTION_CONTEXT_SQL, {"execution_context_id": execution_context_id}).first()
    return row[0] if row is not None else None


def _fetch_default_trading_account_status(engine: Engine, *, user_id: uuid.UUID) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(_TRADING_ACCOUNT_SQL, {"user_id": user_id}).first()
    return row[0] if row is not None else None


def _fetch_active_strategies(engine: Engine, *, execution_context_id: uuid.UUID) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(_ACTIVE_STRATEGIES_SQL, {"execution_context_id": execution_context_id}).mappings().all()
    return [dict(r) for r in rows]


def _seconds_since_last_risk_decision(engine: Engine, *, strategy_id: uuid.UUID) -> float | None:
    with engine.connect() as conn:
        row = conn.execute(_LAST_RISK_DECISION_SQL, {"strategy_id": strategy_id}).first()
    if row is None:
        return None
    last_at = row[0]
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - last_at).total_seconds()


def _has_portfolio_snapshot(engine: Engine, *, execution_context_id: uuid.UUID) -> bool:
    with engine.connect() as conn:
        row = conn.execute(_PORTFOLIO_SNAPSHOT_SQL, {"execution_context_id": execution_context_id}).first()
    return row is not None


def _has_position_snapshot(engine: Engine, *, execution_context_id: uuid.UUID, symbol: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            _POSITION_SNAPSHOT_SQL, {"execution_context_id": execution_context_id, "symbol": symbol}
        ).first()
    return row is not None


def _latest_portfolio_risk(engine: Engine, *, execution_context_id: uuid.UUID) -> dict | None:
    """Return the latest account-risk values written by Portfolio Worker.

    A missing snapshot is not treated as a fabricated zero balance: Paper
    options remain reviewable but cannot be silently approved without a
    buying-power observation.
    """
    with engine.connect() as conn:
        row = conn.execute(_LATEST_PORTFOLIO_RISK_SQL, {"execution_context_id": execution_context_id}).mappings().first()
    return dict(row) if row is not None else None


def _evaluate_option_controls(
    engine: Engine,
    *,
    payload: dict,
    strategy: dict,
    execution_context_kind: str | None,
) -> list[tuple[str, str]]:
    """Validate the fully selected long option before Order Worker.

    This is intentionally a pure, deterministic gate. It never selects a
    contract and never calls Alpaca; selection happens upstream and the
    resulting instrument is revalidated here as a defence-in-depth boundary.
    """
    raw = payload.get("option_instrument")
    if not raw:
        return []
    findings: list[tuple[str, str]] = []
    try:
        instrument = OptionInstrument.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - malformed upstream data is a risk rejection
        return [(REJECTED, f"option instrument invalide : {exc}")]

    underlying = str(payload.get("symbol") or "").upper()
    if instrument.underlying_symbol.upper() != underlying:
        findings.append((REJECTED, "le sous-jacent de l'option ne correspond pas au symbole de la stratégie"))

    proposed_signal = payload.get("proposed_signal")
    expected_type = "call" if proposed_signal == "BUY" else "put" if proposed_signal == "SELL" else None
    if expected_type is None or instrument.option_type != expected_type:
        findings.append((REJECTED, "le type call/put ne correspond pas au signal directionnel"))

    dte = (instrument.expiration_date - datetime.now(UTC).date()).days
    if dte < OPTIONS_MIN_DTE or dte > OPTIONS_MAX_DTE:
        findings.append(
            (REJECTED, f"expiration option hors fenêtre ({dte} DTE, attendu {OPTIONS_MIN_DTE}-{OPTIONS_MAX_DTE})")
        )
    if instrument.quantity > OPTIONS_MAX_CONTRACTS or not float(instrument.quantity).is_integer():
        findings.append((REJECTED, f"quantité optionnelle supérieure à la limite ({OPTIONS_MAX_CONTRACTS} contrat(s))"))
    if instrument.bid_price > instrument.ask_price:
        findings.append((REJECTED, "cotation option invalide (bid supérieur à ask)"))
    if instrument.spread_pct > OPTIONS_MAX_SPREAD_PCT:
        findings.append((REJECTED, f"spread option trop large ({instrument.spread_pct:.2%}, maximum {OPTIONS_MAX_SPREAD_PCT:.2%})"))
    expected_premium = instrument.ask_price * instrument.contract_size * instrument.quantity
    if instrument.estimated_premium > OPTIONS_MAX_PREMIUM_PER_ORDER or instrument.max_loss > OPTIONS_MAX_PREMIUM_PER_ORDER:
        findings.append(
            (REJECTED, f"prime/perte maximale optionnelle supérieure à {OPTIONS_MAX_PREMIUM_PER_ORDER:.2f}")
        )
    if abs(instrument.estimated_premium - expected_premium) > 0.05 or abs(instrument.max_loss - instrument.estimated_premium) > 0.05:
        findings.append((REJECTED, "prime estimée et perte maximale ne correspondent pas au prix ask/quantité"))

    # In PAPER, compare the debit to the latest real snapshot when available.
    # Replay has no brokerage account and is handled by Order Worker as a
    # deferred simulation.
    if execution_context_kind == "PAPER":
        snapshot = _latest_portfolio_risk(engine, execution_context_id=strategy["execution_context_id"])
        if snapshot is None or snapshot.get("buying_power") is None:
            findings.append((REQUIRES_APPROVAL, "buying power indisponible : attendre un portfolio_snapshot Paper récent"))
        elif float(snapshot["buying_power"]) < instrument.estimated_premium:
            findings.append((REJECTED, "buying power Paper insuffisant pour la prime optionnelle"))
    return findings


def _evaluate_controls(
    engine: Engine,
    redis_client: redis.Redis,
    *,
    payload: dict,
    strategy: dict,
    execution_context_kind: str | None,
) -> list[tuple[str, str]]:
    """Retourne la liste EXHAUSTIVE des constats (tier, raison) — un constat
    par contrôle qui n'est pas un "tout va bien" silencieux (voir docstring
    du module : les 16 contrôles sont tous évalués, mais seuls ceux qui
    signalent quelque chose ajoutent une raison — pas de bruit "OK" x16 sur
    chaque décision nominale)."""
    findings: list[tuple[str, str]] = []
    symbol = payload.get("symbol")
    execution_context_id = strategy["execution_context_id"]
    strategy_id = strategy["strategy_id"]

    # 1. Kill switch — veto absolu, jamais contourné, jamais assoupli.
    if get_trading_kill_switch_engaged(redis_client, default=False):
        findings.append((REJECTED, "kill switch trading engagé — rejet automatique, prioritaire sur tout le reste"))

    # 2. Contexte d'exécution — PAPER ou REPLAY autorisés, DRY_RUN rejeté.
    if execution_context_kind is None:
        findings.append((REJECTED, "contexte d'exécution introuvable"))
    elif execution_context_kind not in ("PAPER", "REPLAY"):
        findings.append(
            (REJECTED, f"contexte d'exécution de type {execution_context_kind!r} non autorisé (PAPER ou REPLAY uniquement)")
        )

    # 3. Compte de trading connecté — uniquement pertinent en PAPER (REPLAY
    #    est une simulation sans compte réel, voir B06).
    if execution_context_kind == "PAPER":
        account_status = _fetch_default_trading_account_status(engine, user_id=strategy["user_id"])
        if account_status != "connected":
            findings.append(
                (
                    REJECTED,
                    f"aucun compte de trading connecté (statut constaté : {account_status!r}, attendu 'connected')",
                )
            )

    # 4. Stratégie encore ACTIVE — revérifié au moment de la décision, pas
    #    fait confiance à l'état au moment de la proposition (le temps a pu
    #    passer, l'utilisateur a pu la mettre en pause entre-temps).
    if strategy["status"] != "ACTIVE":
        findings.append((REJECTED, f"stratégie non ACTIVE au moment de la décision (statut actuel : {strategy['status']})"))

    # 5. Fraîcheur des données de marché.
    parsed_ts = _parse_iso_timestamp(payload.get("market_data_timestamp"))
    age_seconds = (datetime.now(UTC) - parsed_ts).total_seconds() if parsed_ts is not None else None
    if age_seconds is None or age_seconds > MAX_CRITIQUE_AGE_SECONDS:
        findings.append(
            (
                REJECTED,
                f"données de marché obsolètes (âge {age_seconds}s, seuil {MAX_CRITIQUE_AGE_SECONDS}s)"
                if age_seconds is not None
                else "horodatage de marché absent ou illisible",
            )
        )

    # 6/7. Limites actives-stratégies / symboles cumulés — défense en
    #      profondeur, indépendante des limites déjà posées côté CRUD
    #      (`backend/app/strategy_instances.py`).
    active_strategies = _fetch_active_strategies(engine, execution_context_id=execution_context_id)
    if len(active_strategies) > MAX_ACTIVE_STRATEGIES:
        findings.append(
            (
                REJECTED,
                f"nombre de stratégies actives ({len(active_strategies)}) dépasse la limite ({MAX_ACTIVE_STRATEGIES}) — anomalie",
            )
        )
    cumulative_symbols: set[str] = set()
    for s in active_strategies:
        symbols = s.get("symbols")
        if isinstance(symbols, list):
            cumulative_symbols.update(str(x) for x in symbols)
    if len(cumulative_symbols) > MAX_CUMULATIVE_SYMBOLS:
        findings.append(
            (
                REJECTED,
                f"nombre de symboles cumulés ({len(cumulative_symbols)}) dépasse la limite ({MAX_CUMULATIVE_SYMBOLS}) — anomalie",
            )
        )

    # 8. Protection obligatoire — spécifique au type de stratégie (voir
    #    docstring du module : pas de `stop_loss_pct` rétroactif sur le
    #    schéma déjà livré de la stratégie IA, sa protection est le flag
    #    `require_human_approval`).
    params = strategy.get("parameters") or {}
    if strategy["type_code"] == AI_STRATEGY_TYPE_CODE:
        if params.get("require_human_approval") is not True:
            findings.append((REJECTED, "stratégie IA sans exigence d'approbation humaine (require_human_approval doit être true)"))
    else:
        stop_loss_pct = params.get("stop_loss_pct")
        if not isinstance(stop_loss_pct, int | float) or stop_loss_pct <= 0:
            findings.append((REJECTED, "protection stop-loss obligatoire manquante ou invalide (stop_loss_pct)"))

    # 9. Cooldown — délai minimum entre deux décisions de risque pour cette
    #    même stratégie (frein de rythme, rejet automatique — pas une simple
    #    alerte, un humain "approuvant" ne rend pas la décision moins rapide).
    elapsed = _seconds_since_last_risk_decision(engine, strategy_id=strategy_id)
    if elapsed is not None and elapsed < COOLDOWN_SECONDS:
        findings.append(
            (REJECTED, f"cooldown actif (dernière décision de risque il y a {elapsed:.0f}s, minimum {COOLDOWN_SECONDS}s)")
        )

    # 10. Politique d'approbation — la proposition D'ORIGINE (pas la
    #     critique) a levé `requires_human_approval`.
    proposal_risk_flags = payload.get("proposal_risk_flags") or []
    if "requires_human_approval" in proposal_risk_flags:
        findings.append((REQUIRES_APPROVAL, "approbation humaine requise par la proposition d'origine (requires_human_approval)"))

    # Options have a concrete debit and quantity, so they use the dedicated
    # gates above instead of the legacy equity controls that intentionally
    # reported an unverifiable notional in V1.
    option_findings = _evaluate_option_controls(
        engine,
        payload=payload,
        strategy=strategy,
        execution_context_kind=execution_context_kind,
    )
    findings.extend(option_findings)
    if payload.get("option_instrument"):
        return findings

    # 11-15. Cinq contrôles honnêtement IMPOSSIBLES à vérifier en V1 — pas
    #        seulement "tant que B18 n'existe pas" (correction du 26/08, voir
    #        D042 dans AVANCEMENT.md §37 et R17). Avant cette correction, les
    #        4 premiers étaient conditionnés à `not has_portfolio`/
    #        `not has_position` : une fois B18 livré (portfolio_snapshots/
    #        positions_snapshots réellement écrits), ils se seraient tus
    #        SILENCIEUSEMENT — un `REQUIRES_APPROVAL` honnête aurait disparu
    #        sans qu'aucune limite n'ait jamais été réellement vérifiée. La
    #        VRAIE raison de l'impossibilité n'est pas "pas de donnée
    #        portefeuille" (B18 la fournit), c'est "aucune LIMITE de risque
    #        configurée nulle part dans le système" (pas de daily-loss-limit,
    #        pas d'exposure-limit, pas de comparaison notional-vs-buying-power
    #        — B18 ne construit délibérément aucune de ces limites, voir son
    #        propre AVANCEMENT.md). Ces 5 constats sont donc désormais
    #        INCONDITIONNELS, comme le contrôle #15 l'a toujours été — la
    #        présence ou l'absence de snapshot n'y change plus rien, elle est
    #        seulement mentionnée en complément quand elle manque encore.
    has_portfolio = _has_portfolio_snapshot(engine, execution_context_id=execution_context_id)
    portfolio_note = "" if has_portfolio else " (et aucun portfolio_snapshot disponible pour l'instant)"
    findings.append(
        (
            REQUIRES_APPROVAL,
            f"argent disponible (buying power) : impossible à vérifier — aucune limite de notional/buying power configurée dans le système{portfolio_note}",
        )
    )
    findings.append(
        (
            REQUIRES_APPROVAL,
            f"perte quotidienne : impossible à vérifier — aucune limite de perte quotidienne configurée dans le système{portfolio_note}",
        )
    )
    findings.append(
        (
            REQUIRES_APPROVAL,
            f"exposition totale du portefeuille : impossible à vérifier — aucune limite d'exposition totale configurée dans le système{portfolio_note}",
        )
    )
    has_position = symbol is not None and _has_position_snapshot(
        engine, execution_context_id=execution_context_id, symbol=symbol
    )
    position_note = "" if has_position else " (et aucune positions_snapshot disponible pour l'instant)"
    findings.append(
        (
            REQUIRES_APPROVAL,
            f"exposition sur {symbol} : impossible à vérifier — aucune limite d'exposition par symbole configurée dans le système{position_note}",
        )
    )
    # 15. Notional de l'ordre — B17 (Order Worker) est livré mais ne calcule
    #     délibérément AUCUNE quantité/notional (D040 « Aucun ordre live
    #     possible » = comportement permanent V1, `sizing_pending` reste
    #     vrai) : `last_close` donne un prix de référence, jamais un
    #     notional proposé à comparer à une limite. Déjà inconditionnel
    #     avant cette correction — seul le libellé est mis à jour (B17 existe
    #     désormais, ce n'est plus "pas construit" mais "construit sans
    #     dimensionnement par choix assumé").
    findings.append(
        (
            REQUIRES_APPROVAL,
            "notional de l'ordre : impossible à vérifier — aucune logique de dimensionnement d'ordre (D040, sizing_pending reste vrai en V1)",
        )
    )

    return findings


def _combine_outcome(findings: list[tuple[str, str]]) -> RiskDecisionResult:
    if not findings:
        return RiskDecisionResult(outcome=APPROVED, reasons=[], adjustments={})
    worst_tier = max((tier for tier, _ in findings), key=lambda t: _TIER_PRECEDENCE[t])
    return RiskDecisionResult(outcome=worst_tier, reasons=[reason for _, reason in findings], adjustments={})


def _record_and_publish(
    engine: Engine,
    redis_client: redis.Redis,
    *,
    result: RiskDecisionResult,
    agent_decision_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    user_id: uuid.UUID | None,
    strategy_id: uuid.UUID,
    symbol: str | None,
    last_close: float | None,
    option_instrument: dict | None,
    market_data_timestamp: str | None,
    correlation_id: uuid.UUID,
    causation_id: uuid.UUID,
) -> None:
    decision_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            _DECISION_INSERT_SQL,
            {
                "id": decision_id,
                "execution_context_id": execution_context_id,
                "agent_decision_id": agent_decision_id,
                "outcome": result.outcome,
                "reasons": json.dumps(result.reasons),
                "adjustments": json.dumps(result.adjustments),
                "correlation_id": correlation_id,
            },
        )

        if user_id is not None:
            # §B28 (D073) — voir docstring du module.
            conn.execute(
                _AGENT_MESSAGE_INSERT_SQL,
                {
                    "id": uuid.uuid4(),
                    "user_id": user_id,
                    "execution_context_id": execution_context_id,
                    "conversation_thread_id": correlation_id,
                    "state": "rejected" if result.outcome == "REJECTED" else "completed",
                    "content": _agent_message_content(result.outcome, result.reasons),
                    "payload": json.dumps(
                        {
                            "agent_decision_id": str(agent_decision_id),
                            "risk_decision_id": str(decision_id),
                            "decision_type": "RISK_DECISION",
                            "outcome": result.outcome,
                            "reasons": result.reasons,
                            "strategy_id": str(strategy_id),
                            "symbol": symbol,
                            "market_data_timestamp": market_data_timestamp,
                            "option_instrument": option_instrument,
                        }
                    ),
                },
            )

    envelope = EventEnvelope(
        event_type="risk.validation.completed",
        correlation_id=correlation_id,
        causation_id=causation_id,
        user_id=user_id,
        execution_context_id=execution_context_id,
        payload={
            "risk_decision_id": str(decision_id),
            "agent_decision_id": str(agent_decision_id),
            "strategy_id": str(strategy_id),
            "symbol": symbol,
            "outcome": result.outcome,
            "reasons": result.reasons,
            "adjustments": result.adjustments,
            # §B17 — complété rétroactivement (même principe que le
            # complément B14→B15) : l'Order Worker a besoin d'un prix de
            # référence pour calculer les jambes d'un bracket order à
            # partir de stop_loss_pct/take_profit_pct. Simple passthrough
            # de la valeur déjà reçue dans `risk.critique.completed` —
            # jamais recalculé ici (non-IA, B15 ne regarde pas les prix).
            "last_close": last_close,
            "option_instrument": option_instrument,
        },
    )
    publish_event(redis_client, Streams.RISK_VALIDATION_COMPLETED, envelope)
    logger.info(
        "risk.validation.completed publié",
        extra={"correlation_id": str(correlation_id), "outcome": result.outcome},
    )


def _process_envelope(engine: Engine, redis_client: redis.Redis, envelope: EventEnvelope) -> None:
    payload = envelope.payload or {}
    strategy_id_raw = payload.get("strategy_id")
    symbol = payload.get("symbol")
    market_data_timestamp = payload.get("market_data_timestamp")
    if not strategy_id_raw or not symbol or not market_data_timestamp:
        logger.error("critique mal formée, ignorée (champs requis manquants)")
        return
    strategy_id = uuid.UUID(str(strategy_id_raw))

    agent_decision_id = _find_critique_agent_decision_id(
        engine, strategy_id=strategy_id, symbol=symbol, market_data_timestamp=market_data_timestamp
    )
    if agent_decision_id is None:
        # Ne devrait pas arriver en fonctionnement normal (le Risk Critic
        # Agent committe toujours la ligne `agent_decisions` AVANT de
        # publier `risk.critique.completed`) — mais `risk_decisions.
        # agent_decision_id` est NOT NULL : impossible de produire une
        # décision sans cette clé. Log et abandon, jamais de FK inventée.
        logger.error(
            "impossible de retrouver la décision CRITIQUE correspondante, décision de risque abandonnée",
            extra={"strategy_id": str(strategy_id), "symbol": symbol},
        )
        return

    if _already_decided(engine, agent_decision_id=agent_decision_id):
        logger.info("critique déjà validée, ignorée", extra={"agent_decision_id": str(agent_decision_id)})
        return

    strategy = _fetch_strategy(engine, strategy_id=strategy_id)
    if strategy is None:
        logger.error("stratégie introuvable, décision de risque abandonnée", extra={"strategy_id": str(strategy_id)})
        return

    execution_context_kind = _fetch_execution_context_kind(engine, execution_context_id=strategy["execution_context_id"])

    findings = _evaluate_controls(
        engine, redis_client, payload=payload, strategy=strategy, execution_context_kind=execution_context_kind
    )
    result = _combine_outcome(findings)

    _record_and_publish(
        engine,
        redis_client,
        result=result,
        agent_decision_id=agent_decision_id,
        execution_context_id=strategy["execution_context_id"],
        user_id=strategy["user_id"],
        strategy_id=strategy_id,
        symbol=symbol,
        last_close=payload.get("last_close"),
        option_instrument=payload.get("option_instrument"),
        market_data_timestamp=market_data_timestamp,
        correlation_id=envelope.correlation_id,
        causation_id=envelope.event_id,
    )


def tick(engine: Engine, redis_client: redis.Redis) -> None:
    consumer = EventConsumer(
        redis_client,
        stream=Streams.RISK_CRITIQUE_COMPLETED,
        group=GROUP_NAME,
        consumer_name=CONSUMER_NAME,
    )
    consumer.ensure_group()

    for message in consumer.read(count=READ_COUNT, block_ms=READ_BLOCK_MS):
        try:
            _process_envelope(engine, redis_client, message.envelope)
            consumer.ack(message.message_id)
        except Exception:  # noqa: BLE001 — un message en échec ne doit jamais arrêter le tick (§B04 retry/dead-letter)
            logger.exception("échec du traitement d'une critique de risque")
            consumer.fail(message.message_id, message.delivery_count)

    for message in consumer.reclaim_stale(idle_ms=RECLAIM_IDLE_MS):
        try:
            _process_envelope(engine, redis_client, message.envelope)
            consumer.ack(message.message_id)
        except Exception:  # noqa: BLE001 — voir commentaire ci-dessus
            logger.exception("échec du traitement d'une critique reprise (PEL)")
            consumer.fail(message.message_id, message.delivery_count)


if __name__ == "__main__":
    run_service("risk-engine", tick)
