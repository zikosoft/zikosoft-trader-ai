"""B12 — définition (au sens B11 : `StrategyDefinition` en mémoire) de la
stratégie "AI Market Agent Strategy" : troisième stratégie prédéfinie
livrée pour le registre B11, et **première stratégie IA réelle** du projet
(`required_capabilities=["ai"]`) — jusqu'ici seule la branche de saut du
Strategy Agent (B13) existait pour ce cas, jamais exercée faute de
stratégie candidate (voir AVANCEMENT.md, limites honnêtes B13/B14)."""

from __future__ import annotations

from shared.strategy_registry import StrategyDefinition

# Même convention que les deux autres stratégies : pas de champ "symbole"
# ici (§B12 "Symboles" — porté par `Strategy.symbols`, colonne dédiée B03,
# identique pour toutes les stratégies, IA ou non).
PARAMETER_SCHEMA = {
    "type": "object",
    "properties": {
        "timeframe": {"type": "string", "enum": ["1Min", "5Min", "15Min", "1Hour", "1Day"]},
        # §B12 "Fréquence d'analyse" — informationnel/contextuel seulement,
        # voir la limite honnête documentée dans engine.py et AVANCEMENT.md :
        # le Strategy Agent évalue TOUTES les stratégies actives à chaque
        # tick du Market Agent (cadence globale, B10), il n'existe pas
        # encore de planificateur par-stratégie pour espacer réellement les
        # appels IA d'une instance donnée.
        "analysis_frequency": {"type": "string", "enum": ["1Min", "5Min", "15Min", "1Hour", "1Day"]},
        # §B12 "Risk posture" — ton/tolérance transmis tel quel dans le
        # prompt IA (voir engine._build_prompt), n'affecte aucun calcul
        # déterministe côté code.
        "risk_posture": {"type": "string", "enum": ["conservative", "balanced", "aggressive"]},
        # §B12 "Confiance minimale" — RÉELLEMENT appliqué par engine.evaluate() :
        # toute sortie IA dont la confiance est strictement inférieure à ce
        # seuil est rétrogradée en HOLD avant de quitter le moteur (pas
        # seulement une indication pour le prompt).
        "min_confidence": {"type": "integer", "minimum": 0, "maximum": 10000},
        # §B12 "Maximum notional" — transmis comme contexte au prompt IA
        # (une consigne de taille de position à respecter dans son
        # raisonnement) ; limite honnête documentée dans engine.py : cette
        # stratégie ne peut PAS elle-même bloquer un ordre qui dépasserait
        # ce montant, aucun ordre n'existe encore (B17 Order Worker pas
        # construit) — l'application financière réelle d'un plafond de
        # notional est le rôle du futur Risk Engine (B15).
        "max_notional_usd": {"type": "number", "exclusiveMinimum": 0},
        # §B12 "Validation humaine configurable" — RÉELLEMENT appliqué :
        # tout signal non-HOLD produit avec ce paramètre à `true` reçoit le
        # risk_flag `requires_human_approval`.
        "require_human_approval": {"type": "boolean"},
    },
    "required": [
        "timeframe",
        "analysis_frequency",
        "risk_posture",
        "min_confidence",
        "max_notional_usd",
        "require_human_approval",
    ],
}

UI_SCHEMA = {
    "timeframe": {"widget": "select", "label": "Intervalle des bougies", "order": 1},
    "analysis_frequency": {"widget": "select", "label": "Fréquence d'analyse cible", "order": 2},
    "risk_posture": {"widget": "select", "label": "Posture de risque", "order": 3},
    "min_confidence": {"widget": "number", "label": "Confiance minimale (points de base)", "order": 4},
    "max_notional_usd": {"widget": "number", "label": "Notional maximal ($)", "order": 5},
    "require_human_approval": {"widget": "checkbox", "label": "Validation humaine requise", "order": 6},
}

DEFAULTS_BY_PROFILE = {
    # §D026 gouvernance des coûts — profil beginner volontairement le plus
    # prudent : confiance minimale élevée, validation humaine obligatoire.
    "beginner": {
        "timeframe": "1Day",
        "analysis_frequency": "1Day",
        "risk_posture": "conservative",
        "min_confidence": 7000,
        "max_notional_usd": 500.0,
        "require_human_approval": True,
    },
    "advanced": {
        "timeframe": "15Min",
        "analysis_frequency": "15Min",
        "risk_posture": "balanced",
        "min_confidence": 6000,
        "max_notional_usd": 2000.0,
        "require_human_approval": True,
    },
}

REQUIRED_MARKET_DATA = {
    "bars": {"timeframes": ["1Min", "5Min", "15Min", "1Hour", "1Day"], "lookback": 500},
}

DEFINITION = StrategyDefinition(
    type_code="ai_market_agent_strategy",
    version="1.0.0",
    name="AI Market Agent Strategy",
    description=(
        "Analyse qualitative d'un symbole par Claude (AIProvider, D017) à partir des dernières "
        "clôtures — signal BUY/SELL/HOLD avec confiance et raisonnement en langage naturel. "
        "Sortie IA revalidée strictement (D022) ; confiance minimale et validation humaine "
        "appliquées par le moteur avant publication ; repli HOLD explicite si l'IA est "
        "indisponible ou répond de façon invalide — jamais un signal fabriqué."
    ),
    parameter_schema=PARAMETER_SCHEMA,
    ui_schema=UI_SCHEMA,
    defaults_by_profile=DEFAULTS_BY_PROFILE,
    required_market_data=REQUIRED_MARKET_DATA,
    # §D017/D022 — seule stratégie du registre à déclarer une capacité :
    # consommée par le Strategy Agent (B13) pour construire un AIProvider
    # et appeler `evaluate(bars, params, ai_provider=...)` au lieu du
    # `evaluate(bars, params)` à 2 arguments des stratégies déterministes.
    required_capabilities=["ai"],
)
