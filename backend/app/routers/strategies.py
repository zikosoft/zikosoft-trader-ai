"""Route de lecture du registre de stratégies (B11) — §"Endpoint liste des
définitions". Lit la table `strategy_definitions` déjà synchronisée depuis
le dossier `strategies/` au démarrage (voir `backend/app/main.py` et
`backend/app/strategy_sync.py`) : la route elle-même ne réimporte jamais de
code Python à la demande (§B11 "pas d'exécution arbitraire")."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import StrategyDefinition as StrategyDefinitionRow
from ..models import User
from ..schemas.strategy_definitions import StrategyDefinitionOut

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def _to_out(row: StrategyDefinitionRow) -> StrategyDefinitionOut:
    manifest = row.manifest or {}
    return StrategyDefinitionOut(
        id=row.id,
        type_code=row.type_code,
        version=row.version,
        name=manifest.get("name", row.type_code),
        description=manifest.get("description", ""),
        parameter_schema=row.parameter_schema,
        ui_schema=row.ui_schema,
        defaults_by_profile=row.defaults_by_profile,
        required_market_data=row.required_market_data,
        required_capabilities=manifest.get("required_capabilities", []),
    )


@router.get("/definitions", response_model=list[StrategyDefinitionOut])
def list_strategy_definitions(
    db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> list[StrategyDefinitionOut]:
    rows = (
        db.execute(
            select(StrategyDefinitionRow)
            .where(StrategyDefinitionRow.is_active.is_(True))
            .order_by(StrategyDefinitionRow.type_code)
        )
        .scalars()
        .all()
    )
    return [_to_out(row) for row in rows]
