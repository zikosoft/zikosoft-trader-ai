"""`StrategyProposal` — sortie structurée commune du Strategy Agent (B13),
décision D022 ("sortie structurée : tool-use natif Claude + validation
Pydantic stricte").

Le point clé de D022 (§AVANCEMENT.md B13) est que TOUTE proposition de
stratégie passe par cette même validation stricte, quelle que soit sa
source — que le calcul soit 100% déterministe (ex.
`moving_average_crossover`, B12, `required_capabilities=[]`) ou qu'il vienne
un jour d'un appel `AIProvider.structured_complete()` (D017, aucune
stratégie IA n'existe encore, voir `strategies/`). Le Strategy Agent ne fait
donc jamais confiance directement à la sortie brute d'un module de
stratégie — elle est toujours revalidée ici avant d'être enregistrée
(`AgentDecision`/`StrategyRun`) ou publiée (`strategy.proposal.created`).
Une sortie qui échoue cette validation ne doit jamais atteindre le Risk
Engine (critère d'acceptation B13) — voir `agents/strategy_agent/main.py`
pour le repli HOLD appliqué dans ce cas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .options import OptionInstrument

Signal = Literal["BUY", "SELL", "HOLD"]


class StrategyProposal(BaseModel):
    """Contrat normalisé — voir docstring du module. `confidence` en points
    de base (0-10000), même convention que `StrategyRun.confidence`
    (`backend/app/models/strategies.py`)."""

    model_config = ConfigDict(frozen=True)

    signal: Signal
    confidence: int = Field(ge=0, le=10000)
    reasoning: str = Field(min_length=1, max_length=4000)
    risk_flags: list[str] = Field(default_factory=list)
    option_instrument: OptionInstrument | None = None
