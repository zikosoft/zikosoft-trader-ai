"""Schémas de lecture de l'Agent Room (§B28) — voir `backend/app/agent_room.py`
pour la justification complète de chaque source de données."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from shared.options import OptionInstrument


class AgentMessageOut(BaseModel):
    id: uuid.UUID
    agent_type: str
    conversation_thread_id: uuid.UUID
    state: str
    content: str
    payload: dict
    occurred_at: datetime

    model_config = {"from_attributes": True}


class AgentMessagesResponse(BaseModel):
    messages: list[AgentMessageOut]


class DecisionChainProposalOut(BaseModel):
    id: uuid.UUID
    outcome: str
    confidence: int | None
    reasoning_text: str | None
    risk_flags: list
    option_instrument: OptionInstrument | None
    created_at: datetime


class DecisionChainCritiqueOut(BaseModel):
    id: uuid.UUID
    outcome: str
    confidence: int | None
    reasoning_text: str | None
    risk_flags: list
    created_at: datetime


class DecisionChainRiskDecisionOut(BaseModel):
    id: uuid.UUID
    outcome: str
    reasons: list
    adjustments: dict
    created_at: datetime


class DecisionChainExplanationOut(BaseModel):
    id: uuid.UUID
    outcome: str
    novice_summary: str | None
    expert_summary: str | None
    created_at: datetime


class DecisionChainOrderOut(BaseModel):
    id: uuid.UUID
    symbol: str
    side: str
    asset_class: str
    option_instrument: OptionInstrument | None
    order_type: str
    time_in_force: str
    status: str
    quantity: float | None
    notional: float | None
    filled_at: datetime | None
    submitted_at: datetime | None


class DecisionChainResponse(BaseModel):
    strategy_id: uuid.UUID
    strategy_name: str | None
    strategy_type_code: str | None
    symbol: str
    market_data_timestamp: str | None
    proposal: DecisionChainProposalOut | None
    critique: DecisionChainCritiqueOut | None
    risk_decision: DecisionChainRiskDecisionOut | None
    explanation: DecisionChainExplanationOut | None
    order: DecisionChainOrderOut | None
