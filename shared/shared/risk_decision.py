"""`RiskDecisionResult` — sortie normalisée du Risk Engine déterministe
(B15). Contrairement à `StrategyProposal`/`RiskCritique` (B13/B14), rien
ici ne vient d'un fournisseur IA (§D005 — le Risk Engine est
volontairement non-IA) : il n'y a donc pas de sortie de modèle à
revalider. Ce contrat existe malgré tout pour la même raison que
`shared.errors` normalise les réponses HTTP — défense en profondeur contre
un bug interne qui produirait une valeur d'outcome incohérente (ex. faute
de frappe dans une chaîne littérale ailleurs dans le code), et pour donner
au reste du pipeline (B16 Execution & Explanation Agent, B28 Agent Room) un
contrat typé unique à consommer plutôt qu'un dict non structuré.

**`ADJUSTED` existe dans le vocabulaire et le schéma (`risk_decisions.
outcome`, colonne `String(30)` sans CHECK — voir `backend/app/models/
risk.py`) mais n'est JAMAIS produit par cette V1** : ajuster une décision
suppose une vraie logique de dimensionnement d'ordre (notional, quantité)
qui n'existe pas encore (B17 Order Worker, pas construit) — documenté
comme limite V1 dans AVANCEMENT.md, pas caché. Un futur brique pourra
introduire `ADJUSTED` une fois B17 livré, sans migration de schéma."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RiskOutcome = Literal["APPROVED", "ADJUSTED", "REQUIRES_APPROVAL", "REJECTED"]


class RiskDecisionResult(BaseModel):
    """`reasons` : liste EXHAUSTIVE des constats de TOUS les contrôles
    évalués (pas seulement ceux qui ont motivé l'outcome final) — cohérent
    avec la logique de combinaison "évaluer tous les contrôles, puis
    combiner par sévérité" du Risk Engine (voir `workers/risk_engine/
    main.py::_combine_outcome`). `adjustments` : toujours `{}` en V1 tant
    qu'`ADJUSTED` n'est jamais produit (voir docstring du module) — présent
    dès maintenant pour éviter une migration de schéma future."""

    model_config = ConfigDict(frozen=True)

    outcome: RiskOutcome
    reasons: list[str] = Field(default_factory=list)
    adjustments: dict = Field(default_factory=dict)
