"""Schémas des résumés d'activité "agents" et "risque" (§B26 "Résumé Agent
Room" et "Risque").

Même portée volontairement minimale que `schemas/orders.py` : ce n'est PAS
le futur écran Agent Room complet (Live Debate, Ask Ziko AI, Decision
Details restent des placeholders honnêtes depuis B25, propriété de B28/B29)
mais juste de quoi peupler deux petits widgets de synthèse sur le tableau
de bord principal, à partir de données déjà réellement écrites par le
Strategy Agent/Risk Critic Agent (B13/B14, table `agent_decisions`) et le
Risk Engine déterministe (B15, table `risk_decisions`)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AgentDecisionOut(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID | None
    agent_type: str
    decision_type: str
    outcome: str
    confidence: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RecentAgentDecisionsResponse(BaseModel):
    decisions: list[AgentDecisionOut]


class RiskDecisionOut(BaseModel):
    id: uuid.UUID
    agent_decision_id: uuid.UUID
    outcome: str
    reasons: list
    created_at: datetime

    model_config = {"from_attributes": True}


class RecentRiskDecisionsResponse(BaseModel):
    decisions: list[RiskDecisionOut]
