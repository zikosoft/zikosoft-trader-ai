"""`OrderCommand` — contrat de `order.command.prepared` (B16→B17), validé
côté Order Worker avant tout traitement (checklist B17 "Vérifier
signature/contrat de commande"). Même discipline D022 que les autres
contrats structurés du pipeline (`StrategyProposal`/`RiskCritique`/
`RiskDecisionResult`/`Explanation`) : un payload qui ne valide pas ce
schéma est un signal d'anomalie amont, jamais réparé en silence — voir
`workers/order_worker/main.py::_process_envelope` (dead-letter)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["buy", "sell"]


class OrderCommand(BaseModel):
    """`notional`/`quantity` restent `None` et `sizing_pending` reste
    `True` tant qu'aucune logique de dimensionnement d'ordre n'existe
    (limite V1 assumée, voir B16 D035) — ce contrat les accepte malgré
    tout (types optionnels, pas de contrainte de présence) pour être prêt
    dès qu'un futur brique les fournira, sans nouvelle migration de
    contrat."""

    model_config = ConfigDict(frozen=True)

    strategy_id: uuid.UUID
    risk_decision_id: uuid.UUID
    agent_decision_id: uuid.UUID
    explanation_agent_decision_id: uuid.UUID
    symbol: str = Field(min_length=1, max_length=50)
    side: Side
    order_type: str = Field(default="market", max_length=20)
    time_in_force: str = Field(default="day", max_length=10)
    stop_loss_pct: float | None = Field(default=None, gt=0)
    take_profit_pct: float | None = Field(default=None, gt=0)
    reference_price: float | None = Field(default=None, gt=0)
    notional: float | None = None
    quantity: float | None = None
    sizing_pending: bool = True
    adjustments: dict = Field(default_factory=dict)
