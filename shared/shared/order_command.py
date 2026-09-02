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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .options import OptionInstrument

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
    asset_class: Literal["equity", "option", "crypto"] = "equity"
    order_type: str = Field(default="market", max_length=20)
    time_in_force: str = Field(default="day", max_length=10)
    stop_loss_pct: float | None = Field(default=None, gt=0)
    take_profit_pct: float | None = Field(default=None, gt=0)
    reference_price: float | None = Field(default=None, gt=0)
    notional: float | None = None
    quantity: float | None = None
    sizing_pending: bool = True
    adjustments: dict = Field(default_factory=dict)
    option_instrument: OptionInstrument | None = None

    @model_validator(mode="after")
    def validate_option_order(self) -> "OrderCommand":
        """Keep the existing equity contract permissive while making the
        options path explicit and safe before it reaches the Order Worker."""
        if self.asset_class != "option" and self.option_instrument is not None:
            raise ValueError("option_instrument requires asset_class='option'")
        if self.asset_class != "option":
            return self
        instrument = self.option_instrument
        if instrument is None:
            raise ValueError("option orders require option_instrument")
        if self.symbol != instrument.symbol:
            raise ValueError("option order symbol must match option_instrument.symbol")
        if self.side != "buy":
            raise ValueError("only long option buys are supported")
        if self.order_type != "limit":
            raise ValueError("option orders must use a limit order")
        if self.time_in_force not in {"day", "gtc"}:
            raise ValueError("option orders require day or gtc time_in_force")
        if self.notional is not None:
            raise ValueError("option orders must use quantity, not notional")
        if self.quantity is None or self.quantity < 1 or not float(self.quantity).is_integer():
            raise ValueError("option quantity must be a positive whole number")
        if self.sizing_pending:
            raise ValueError("option orders cannot remain sizing_pending")
        if abs(float(self.quantity) - instrument.quantity) > 1e-9:
            raise ValueError("quantity must match option_instrument.quantity")
        if self.reference_price is None or abs(self.reference_price - instrument.limit_price) > 1e-9:
            raise ValueError("reference_price must match option instrument limit_price")
        return self
