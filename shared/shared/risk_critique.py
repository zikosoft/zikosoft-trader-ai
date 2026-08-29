"""`RiskCritique` — sortie structurée du Risk Critic Agent (B14), même
discipline D022 que `shared.strategy_proposal.StrategyProposal` (B13) :
toute sortie du fournisseur IA est revalidée ici avant tout enregistrement
ou publication, jamais une confiance aveugle dans la réponse brute.

**Rappel critique (D005, §B14 "Règle") : cette critique est CONSULTATIVE —
elle ne contourne jamais le Risk Engine déterministe (B15, pas encore
construit).** Rien, à ce jour, n'agit automatiquement sur une
`RiskCritique` : elle est enregistrée (`AgentDecision`) et publiée
(`risk.critique.completed`) pour que B15/B28 (Agent Room) la consomment
plus tard, mais aucun ordre, aucune exécution, aucun contournement n'en
découle depuis ce module."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Recommendation = Literal["APPROVE", "REDUCE", "REQUIRES_REVIEW", "REJECT"]


class RiskCritique(BaseModel):
    """Contrat normalisé — voir docstring du module. `confidence` en points
    de base (0-10000), même convention que `StrategyProposal`/`StrategyRun`."""

    model_config = ConfigDict(frozen=True)

    recommendation: Recommendation
    confidence: int = Field(ge=0, le=10000)
    reasoning: str = Field(min_length=1, max_length=4000)
    risk_flags: list[str] = Field(default_factory=list)
