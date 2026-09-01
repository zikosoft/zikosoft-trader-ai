"""Lecture des données de l'Agent Room (§B28 "Agent Room") — deux besoins
distincts, alimentés par des tables déjà écrites par B13/B14/B15/B16, avec
un seul ajout réel côté écriture (D073, voir les docstrings des modules
`agents/strategy_agent/main.py`, `agents/risk_critic_agent/main.py`,
`workers/risk_engine/main.py`) : ces trois modules écrivent désormais AUSSI
une ligne `agent_messages` (jusqu'ici seul l'Execution & Explanation Agent,
B16, le faisait), complétant enfin le "Live Debate" que cette table
documentait depuis B03/D018 sans qu'aucun agent ne l'alimente pleinement.

**"Live Debate"** (`list_messages`) : lecture simple, la plus récente
d'abord côté requête puis réordonnée chronologiquement ascendant pour un
rendu façon fil de discussion (même bibliothèque de pattern que
`market.py::list_bars` pour la même raison — le consommateur veut lire du
plus ancien au plus récent).

**"Decision Details"** (`get_decision_chain`) : reconstitue la chaîne
complète PROPOSAL → CRITIQUE → décision Risk Engine → EXPLANATION → Ordre
pour UNE fenêtre de décision (`strategy_id`, `symbol`,
`market_data_timestamp` — la même clé anti-doublon déjà utilisée partout
dans le pipeline, voir `workers/risk_engine/main.py::_find_critique_agent_decision_id`),
PAS par `correlation_id` (qui peut être partagé par plusieurs stratégies
observant le même symbole au même tick du Market Agent — voir D073,
AVANCEMENT.md). Chaque maillon est honnêtement `None` s'il n'a pas encore
eu lieu (chaîne asynchrone : une proposition tout juste publiée peut ne pas
encore avoir de critique) plutôt qu'une erreur — jamais de 404 pour un état
intermédiaire réel."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentDecision, AgentMessage, Order, RiskDecision, Strategy, StrategyDefinition

MAX_MESSAGES_LIMIT = 200
DEFAULT_MESSAGES_LIMIT = 100


def list_messages(db: Session, *, execution_context_id: uuid.UUID, limit: int) -> list[AgentMessage]:
    recent_desc = (
        db.execute(
            select(AgentMessage)
            .where(AgentMessage.execution_context_id == execution_context_id)
            .order_by(AgentMessage.occurred_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(reversed(recent_desc))


def _find_decision(
    db: Session,
    *,
    execution_context_id: uuid.UUID,
    strategy_id: uuid.UUID,
    symbol: str,
    market_data_timestamp: str,
    decision_type: str,
) -> AgentDecision | None:
    return db.execute(
        select(AgentDecision)
        .where(
            AgentDecision.execution_context_id == execution_context_id,
            AgentDecision.strategy_id == strategy_id,
            AgentDecision.decision_type == decision_type,
            AgentDecision.market_data_timestamp == market_data_timestamp,
            AgentDecision.reasoning["symbol"].astext == symbol,
        )
        .order_by(AgentDecision.created_at.desc())
        .limit(1)
    ).scalars().first()


def get_decision_chain(
    db: Session,
    *,
    execution_context_id: uuid.UUID,
    strategy_id: uuid.UUID,
    symbol: str,
    market_data_timestamp: str,
) -> dict:
    proposal = _find_decision(
        db,
        execution_context_id=execution_context_id,
        strategy_id=strategy_id,
        symbol=symbol,
        market_data_timestamp=market_data_timestamp,
        decision_type="PROPOSAL",
    )
    critique = _find_decision(
        db,
        execution_context_id=execution_context_id,
        strategy_id=strategy_id,
        symbol=symbol,
        market_data_timestamp=market_data_timestamp,
        decision_type="CRITIQUE",
    )

    risk_decision: RiskDecision | None = None
    if critique is not None:
        risk_decision = db.execute(
            select(RiskDecision)
            .where(RiskDecision.agent_decision_id == critique.id)
            .order_by(RiskDecision.created_at.desc())
            .limit(1)
        ).scalars().first()

    explanation: AgentDecision | None = None
    if risk_decision is not None:
        explanation = db.execute(
            select(AgentDecision)
            .where(
                AgentDecision.decision_type == "EXPLANATION",
                AgentDecision.reasoning["risk_decision_id"].astext == str(risk_decision.id),
            )
            .order_by(AgentDecision.created_at.desc())
            .limit(1)
        ).scalars().first()

    order: Order | None = None
    if risk_decision is not None:
        order = db.execute(
            select(Order)
            .where(Order.risk_decision_id == risk_decision.id)
            .order_by(Order.created_at.desc())
            .limit(1)
        ).scalars().first()

    strategy_row = db.execute(
        select(Strategy.name, StrategyDefinition.type_code)
        .join(StrategyDefinition, Strategy.strategy_definition_id == StrategyDefinition.id)
        .where(Strategy.id == strategy_id)
    ).first()

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_row.name if strategy_row is not None else None,
        "strategy_type_code": strategy_row.type_code if strategy_row is not None else None,
        "symbol": symbol,
        "market_data_timestamp": market_data_timestamp,
        "proposal": proposal,
        "critique": critique,
        "risk_decision": risk_decision,
        "explanation": explanation,
        "order": order,
    }
