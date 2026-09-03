"""Routes de lecture de l'Agent Room (§B28) — voir `backend/app/agent_room.py`
pour la provenance de chaque donnée. Les deux routes sont scopées par
contexte d'exécution actif (§R06, mêmes principes que
`routers/market.py`/`routers/orders.py`)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from shared.errors import ErrorCode

from .. import agent_room as service
from ..ai_runtime import get_readonly_ai_provider
from ..ask_ziko import MAX_ASK_ZIKO_OUTPUT_TOKENS, answer_decision_question
from ..api_errors import api_error_response
from ..auth import get_current_user
from ..context import active_context, ensure_user_contexts
from ..db import get_db
from ..models import User
from ..redis_client import redis_client
from ..schemas.agent_room import (
    AskZikoRequest,
    AskZikoResponse,
    AgentMessageOut,
    AgentMessagesResponse,
    DecisionChainCritiqueOut,
    DecisionChainExplanationOut,
    DecisionChainOrderOut,
    DecisionChainProposalOut,
    DecisionChainResponse,
    DecisionChainRiskDecisionOut,
)

router = APIRouter(prefix="/api/agents/room", tags=["agents"])


class _NoActiveContext(Exception):
    pass


def _require_active_context_id(db: Session, user: User) -> uuid.UUID:
    contexts = ensure_user_contexts(db, user)
    active = active_context(contexts)
    if active is None:
        raise _NoActiveContext()
    return active.id


def _no_active_context_error() -> JSONResponse:
    return api_error_response(400, ErrorCode.VALIDATION_ERROR, "aucun contexte d'exécution actif")


@router.get("/messages", response_model=AgentMessagesResponse)
def get_messages(
    limit: int = Query(default=service.DEFAULT_MESSAGES_LIMIT, ge=1, le=service.MAX_MESSAGES_LIMIT),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    messages = service.list_messages(db, execution_context_id=context_id, limit=limit)
    return AgentMessagesResponse(messages=[AgentMessageOut.model_validate(m) for m in messages])


@router.get("/decision-chain", response_model=DecisionChainResponse)
def get_decision_chain(
    strategy_id: uuid.UUID,
    symbol: str,
    market_data_timestamp: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    chain = service.get_decision_chain(
        db,
        execution_context_id=context_id,
        strategy_id=strategy_id,
        symbol=symbol.upper(),
        market_data_timestamp=market_data_timestamp,
    )

    proposal = chain["proposal"]
    critique = chain["critique"]
    risk_decision = chain["risk_decision"]
    explanation = chain["explanation"]
    order = chain["order"]

    return DecisionChainResponse(
        strategy_id=chain["strategy_id"],
        strategy_name=chain["strategy_name"],
        strategy_type_code=chain["strategy_type_code"],
        symbol=chain["symbol"],
        market_data_timestamp=chain["market_data_timestamp"],
        proposal=(
            DecisionChainProposalOut(
                id=proposal.id,
                outcome=proposal.outcome,
                confidence=proposal.confidence,
                reasoning_text=(proposal.reasoning or {}).get("text"),
                risk_flags=proposal.risk_flags,
                option_instrument=(proposal.reasoning or {}).get("option_instrument"),
                created_at=proposal.created_at,
            )
            if proposal is not None
            else None
        ),
        critique=(
            DecisionChainCritiqueOut(
                id=critique.id,
                outcome=critique.outcome,
                confidence=critique.confidence,
                reasoning_text=(critique.reasoning or {}).get("text"),
                risk_flags=critique.risk_flags,
                created_at=critique.created_at,
            )
            if critique is not None
            else None
        ),
        risk_decision=(
            DecisionChainRiskDecisionOut(
                id=risk_decision.id,
                outcome=risk_decision.outcome,
                reasons=risk_decision.reasons,
                adjustments=risk_decision.adjustments,
                created_at=risk_decision.created_at,
            )
            if risk_decision is not None
            else None
        ),
        explanation=(
            DecisionChainExplanationOut(
                id=explanation.id,
                outcome=explanation.outcome,
                novice_summary=(explanation.reasoning or {}).get("novice_summary"),
                expert_summary=(explanation.reasoning or {}).get("expert_summary"),
                created_at=explanation.created_at,
            )
            if explanation is not None
            else None
        ),
        order=(
            DecisionChainOrderOut(
                id=order.id,
                symbol=order.symbol,
                side=order.side,
                asset_class=order.asset_class,
                option_instrument=order.option_instrument,
                order_type=order.order_type,
                time_in_force=order.time_in_force,
                status=order.status,
                quantity=float(order.quantity) if order.quantity is not None else None,
                notional=float(order.notional) if order.notional is not None else None,
                filled_at=order.filled_at,
                submitted_at=order.submitted_at,
            )
            if order is not None
            else None
        ),
    )


@router.post("/ask-ziko", response_model=AskZikoResponse)
def ask_ziko(
    payload: AskZikoRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AskZikoResponse | JSONResponse:
    """Explain one selected decision without touching MCP, Alpaca, or orders.

    The route looks up the decision through the same active-context scoped
    query as Decision Details.  It deliberately never accepts a decision
    record from the browser, therefore a question cannot be used to make the
    explainer inspect a different account/context.
    """
    try:
        context_id = _require_active_context_id(db, user)
    except _NoActiveContext:
        return _no_active_context_error()

    chain = service.get_decision_chain(
        db,
        execution_context_id=context_id,
        strategy_id=payload.strategy_id,
        symbol=payload.symbol.upper(),
        market_data_timestamp=payload.market_data_timestamp,
    )
    result = answer_decision_question(
        chain=chain,
        question=payload.question,
        locale=payload.locale,
        provider=get_readonly_ai_provider(redis_client, max_tokens=MAX_ASK_ZIKO_OUTPUT_TOKENS),
    )
    return AskZikoResponse(**result)
