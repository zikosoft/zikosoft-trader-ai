"""Schémas de la lecture "ordres récents" (§B26 "Ordres récents").

Portée volontairement minimale (lecture seule, pas de pagination complète
ni de filtre) : ce n'est pas un écran "Orders" complet (celui-ci reste un
placeholder honnête depuis B25, voir `frontend/src/pages/OrdersPage.tsx`,
"backend prêt B17 UI à venir") mais juste ce qu'il faut pour le widget
"Ordres récents" du tableau de bord principal — même logique que B18 qui
avait construit `GET /api/portfolio/*` en lecture seule pour ses propres
cartes sans construire un écran Portfolio complet."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from shared.options import OptionInstrument


class OrderOut(BaseModel):
    id: uuid.UUID
    symbol: str
    side: str
    asset_class: str
    option_instrument: OptionInstrument | None
    quantity: float | None
    notional: float | None
    order_type: str
    status: str
    submitted_at: datetime | None
    filled_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RecentOrdersResponse(BaseModel):
    orders: list[OrderOut]
