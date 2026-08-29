"""`Explanation` — sortie structurée de l'Execution & Explanation Agent
(B16), même discipline D022 que `StrategyProposal`/`RiskCritique` : toute
sortie du fournisseur IA est revalidée ici avant tout enregistrement ou
publication.

**Rôle strictement narratif — jamais décisionnel.** Contrairement à
`StrategyProposal`/`RiskCritique`, cette structure ne transporte AUCUN
champ qui pourrait ressembler à une décision (pas d'`outcome`, pas de
`recommendation`) : l'Execution & Explanation Agent explique une décision
déjà prise par le Risk Engine déterministe (B15), il ne la reformule
jamais en une décision différente. Le prompt qui produit cette sortie
insiste sur ce point (voir `agents/execution_explanation_agent/main.py`) —
`novice_summary`/`expert_summary` sont une reformulation en langage
naturel de faits déjà figés, jamais une nouvelle analyse."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Explanation(BaseModel):
    """`novice_summary` : quelques phrases en langage simple, pour un
    utilisateur qui découvre le produit. `expert_summary` : plus détaillé,
    peut citer les raisons machine-readable brutes du Risk Engine."""

    model_config = ConfigDict(frozen=True)

    novice_summary: str = Field(min_length=1, max_length=2000)
    expert_summary: str = Field(min_length=1, max_length=4000)
